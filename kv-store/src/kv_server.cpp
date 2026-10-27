#include "kv_server.hpp"
#include "kv_protocol.hpp"

#include <cerrno>
#include <chrono>
#include <cstring>
#include <iostream>

namespace kvstore {

KVServer::KVServer(KVStore& store, const std::string& host, uint16_t port)
    : store_(store), host_(host), port_(port) {
    SocketSubsystem::init();
}

KVServer::~KVServer() {
    stop();
    SocketSubsystem::cleanup();
}

bool KVServer::start() {
    if (running_.load()) {
        return true;
    }

    socket_t s = socket(AF_INET, SOCK_STREAM, 0);
    if (s == INVALID_SOCK) {
        return false;
    }
    listen_sock_.reset(s);

    // Reuse address
    int opt = 1;
#ifdef _WIN32
    setsockopt(listen_sock_.get(), SOL_SOCKET, SO_REUSEADDR, (const char*)&opt, sizeof(opt));
#else
    setsockopt(listen_sock_.get(), SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#endif

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port_);
    if (inet_pton(AF_INET, host_.c_str(), &addr.sin_addr) <= 0) {
        addr.sin_addr.s_addr = htonl(INADDR_ANY);
    }

    if (bind(listen_sock_.get(), (sockaddr*)&addr, sizeof(addr)) == SOCK_ERR) {
        listen_sock_.reset();
        return false;
    }

    // If port 0 was passed, retrieve the dynamically assigned port
    if (port_ == 0) {
        sockaddr_in sin{};
#ifdef _WIN32
        int len = sizeof(sin);
#else
        socklen_t len = sizeof(sin);
#endif
        if (getsockname(listen_sock_.get(), (sockaddr*)&sin, &len) == 0) {
            port_ = ntohs(sin.sin_port);
        }
    }

    if (listen(listen_sock_.get(), 128) == SOCK_ERR) {
        listen_sock_.reset();
        return false;
    }

    running_.store(true);

    // Start background threads
    accept_thread_ = std::thread(&KVServer::listen_loop, this);
    sweep_thread_ = std::thread(&KVServer::background_sweep_loop, this);

    return true;
}

void KVServer::stop() {
    if (!running_.exchange(false)) {
        return;
    }

    // On POSIX Linux, close() does not unblock a blocking accept() call.
    // Making a loopback connection cleanly unblocks accept() across all platforms.
    if (port_ > 0) {
        socket_t wakeup = socket(AF_INET, SOCK_STREAM, 0);
        if (wakeup != INVALID_SOCK) {
            sockaddr_in addr{};
            addr.sin_family = AF_INET;
            addr.sin_port = htons(port_);
            inet_pton(AF_INET, host_.c_str(), &addr.sin_addr);
            connect(wakeup, (sockaddr*)&addr, sizeof(addr));
            close_socket(wakeup);
        }
    }

    // Close listen socket
    listen_sock_.reset();

    if (accept_thread_.joinable()) {
        accept_thread_.join();
    }
    if (sweep_thread_.joinable()) {
        sweep_thread_.join();
    }
}

void KVServer::listen_loop() {
    while (running_.load()) {
        sockaddr_in client_addr{};
#ifdef _WIN32
        int addr_len = sizeof(client_addr);
#else
        socklen_t addr_len = sizeof(client_addr);
#endif
        socket_t client_sock = accept(listen_sock_.get(), (sockaddr*)&client_addr, &addr_len);
        if (!running_.load()) {
            if (client_sock != INVALID_SOCK) {
                close_socket(client_sock);
            }
            break;
        }
        if (client_sock == INVALID_SOCK) {
            continue;
        }

        // Spawn detached worker thread for client
        std::thread([this, client_sock]() {
            handle_client(client_sock);
        }).detach();
    }
}

void KVServer::handle_client(socket_t raw_sock) {
    SocketGuard sock(raw_sock);

    // Set receive timeout (200ms) so worker can exit promptly if server stops
#ifdef _WIN32
    DWORD timeout_ms = 200;
    setsockopt(sock.get(), SOL_SOCKET, SO_RCVTIMEO, (const char*)&timeout_ms, sizeof(timeout_ms));
#else
    struct timeval tv;
    tv.tv_sec = 0;
    tv.tv_usec = 200000;
    setsockopt(sock.get(), SOL_SOCKET, SO_RCVTIMEO, (const void*)&tv, sizeof(tv));
#endif

    std::string buffer;
    char chunk[1024];

    while (running_.load()) {
        int bytes_read = recv(sock.get(), chunk, sizeof(chunk), 0);
        if (bytes_read == 0) {
            break; // Connection gracefully closed by peer
        }
        if (bytes_read < 0) {
#ifdef _WIN32
            int err = WSAGetLastError();
            if (err == WSAETIMEDOUT || err == WSAEWOULDBLOCK) {
                continue; // Timeout expired, loop back and check running_
            }
#else
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) {
                continue; // Timeout expired, loop back and check running_
            }
#endif
            break; // Hard socket error
        }

        buffer.append(chunk, bytes_read);

        size_t newline_pos;
        while ((newline_pos = buffer.find('\n')) != std::string::npos) {
            std::string line = buffer.substr(0, newline_pos);
            buffer.erase(0, newline_pos + 1);

            if (!line.empty() && line.back() == '\r') {
                line.pop_back();
            }

            if (line.empty()) {
                continue;
            }

            bool should_close = false;
            std::string response = ProtocolHandler::execute_command(store_, line, should_close);

            if (!response.empty()) {
                send(sock.get(), response.data(), static_cast<int>(response.size()), 0);
            }

            if (should_close) {
                return;
            }
        }
    }
}

void KVServer::background_sweep_loop() {
    while (running_.load()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        if (running_.load()) {
            store_.cleanup_expired();
        }
    }
}

} // namespace kvstore
