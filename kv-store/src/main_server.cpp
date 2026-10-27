#include "kv_server.hpp"
#include "kv_store.hpp"

#include <csignal>
#include <cstdlib>
#include <iostream>
#include <string>

static std::atomic<bool> g_shutdown{false};

static void sig_handler(int) {
    g_shutdown.store(true);
}

int main(int argc, char* argv[]) {
    std::string host = "127.0.0.1";
    uint16_t port = 6379;
    std::string persistence_file = "dump.kv";

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "-h" && i + 1 < argc) {
            host = argv[++i];
        } else if (arg == "-p" && i + 1 < argc) {
            port = static_cast<uint16_t>(std::atoi(argv[++i]));
        } else if (arg == "-f" && i + 1 < argc) {
            persistence_file = argv[++i];
        } else if (arg == "--help") {
            std::cout << "Usage: kv_server [-h host] [-p port] [-f snapshot_file]\n"
                      << "  -h  Host address to bind (default: 127.0.0.1)\n"
                      << "  -p  Port to listen on (default: 6379)\n"
                      << "  -f  Snapshot persistence file (default: dump.kv)\n";
            return 0;
        }
    }

    std::signal(SIGINT, sig_handler);
#ifndef _WIN32
    std::signal(SIGTERM, sig_handler);
#endif

    std::cout << "========================================================\n"
              << "       KV-Store Server (Redis-compatible text engine)   \n"
              << "========================================================\n"
              << "[+] Host: " << host << ":" << port << "\n"
              << "[+] Persistence: " << persistence_file << "\n";

    kvstore::KVStore store(persistence_file);
    kvstore::KVServer server(store, host, port);

    if (!server.start()) {
        std::cerr << "[-] Error: Failed to start server on " << host << ":" << port << "\n";
        return 1;
    }

    std::cout << "[+] Server listening on port " << server.port() << ". Press Ctrl+C to terminate.\n";

    while (!g_shutdown.load()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }

    std::cout << "\n[*] Shutting down server and persisting snapshot...\n";
    store.save();
    server.stop();
    std::cout << "[+] Server shutdown complete. Goodbye!\n";

    return 0;
}
