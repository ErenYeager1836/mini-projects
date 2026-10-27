#include "net_utils.hpp"
#include <utility>

namespace kvstore {

bool SocketSubsystem::init() {
#ifdef _WIN32
    WSADATA wsa;
    return WSAStartup(MAKEWORD(2, 2), &wsa) == 0;
#else
    return true;
#endif
}

void SocketSubsystem::cleanup() {
#ifdef _WIN32
    WSACleanup();
#endif
}

void close_socket(socket_t s) {
    if (s != INVALID_SOCK) {
#ifdef _WIN32
        closesocket(s);
#else
        close(s);
#endif
    }
}

SocketGuard::SocketGuard(socket_t sock) : sock_(sock) {}

SocketGuard::~SocketGuard() {
    reset();
}

SocketGuard::SocketGuard(SocketGuard&& other) noexcept : sock_(other.sock_) {
    other.sock_ = INVALID_SOCK;
}

SocketGuard& SocketGuard::operator=(SocketGuard&& other) noexcept {
    if (this != &other) {
        reset();
        sock_ = other.sock_;
        other.sock_ = INVALID_SOCK;
    }
    return *this;
}

void SocketGuard::reset(socket_t new_sock) {
    if (sock_ != INVALID_SOCK) {
        close_socket(sock_);
    }
    sock_ = new_sock;
}

socket_t SocketGuard::release() {
    socket_t temp = sock_;
    sock_ = INVALID_SOCK;
    return temp;
}

} // namespace kvstore
