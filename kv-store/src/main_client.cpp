#include "net_utils.hpp"

#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>

int main(int argc, char* argv[]) {
    std::string host = "127.0.0.1";
    uint16_t port = 6379;
    std::string one_shot_cmd = "";

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "-h" && i + 1 < argc) {
            host = argv[++i];
        } else if (arg == "-p" && i + 1 < argc) {
            port = static_cast<uint16_t>(std::atoi(argv[++i]));
        } else if (arg == "--help") {
            std::cout << "Usage: kv_client [-h host] [-p port] [command...]\n";
            return 0;
        } else {
            if (!one_shot_cmd.empty()) {
                one_shot_cmd += " ";
            }
            one_shot_cmd += arg;
        }
    }

    kvstore::SocketSubsystem::init();

    kvstore::socket_t s = socket(AF_INET, SOCK_STREAM, 0);
    if (s == kvstore::INVALID_SOCK) {
        std::cerr << "[-] Error creating socket\n";
        kvstore::SocketSubsystem::cleanup();
        return 1;
    }
    kvstore::SocketGuard sock(s);

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    inet_pton(AF_INET, host.c_str(), &addr.sin_addr);

    if (connect(sock.get(), (sockaddr*)&addr, sizeof(addr)) == kvstore::SOCK_ERR) {
        std::cerr << "[-] Error: Could not connect to kv_server at " << host << ":" << port << "\n";
        kvstore::SocketSubsystem::cleanup();
        return 1;
    }

    auto send_and_receive = [&](const std::string& cmd) -> bool {
        std::string payload = cmd + "\r\n";
        if (send(sock.get(), payload.data(), static_cast<int>(payload.size()), 0) <= 0) {
            std::cerr << "[-] Connection lost while sending\n";
            return false;
        }

        char buffer[2048];
        int bytes = recv(sock.get(), buffer, sizeof(buffer) - 1, 0);
        if (bytes <= 0) {
            std::cerr << "[-] Connection closed by server\n";
            return false;
        }
        buffer[bytes] = '\0';
        std::cout << buffer;
        return true;
    };

    if (!one_shot_cmd.empty()) {
        send_and_receive(one_shot_cmd);
    } else {
        std::cout << "Connected to " << host << ":" << port << ". Type commands (e.g. SET, GET, PING, QUIT):\n";
        std::string line;
        while (true) {
            std::cout << host << ":" << port << "> ";
            if (!std::getline(std::cin, line)) {
                break;
            }
            if (line.empty()) {
                continue;
            }
            if (!send_and_receive(line)) {
                break;
            }
            if (line == "QUIT" || line == "quit") {
                break;
            }
        }
    }

    kvstore::SocketSubsystem::cleanup();
    return 0;
}
