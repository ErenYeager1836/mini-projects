#pragma once

#include "kv_store.hpp"
#include "net_utils.hpp"

#include <atomic>
#include <string>
#include <thread>
#include <vector>

namespace kvstore {

/**
 * Multithreaded TCP server accepting client connections, processing protocol commands,
 * and managing background key expiration cleanup sweeps.
 */
class KVServer {
public:
    KVServer(KVStore& store, const std::string& host = "127.0.0.1", uint16_t port = 6379);
    ~KVServer();

    bool start();
    void stop();
    bool is_running() const { return running_.load(); }
    uint16_t port() const { return port_; }

private:
    void listen_loop();
    void handle_client(socket_t client_sock);
    void background_sweep_loop();

    KVStore& store_;
    std::string host_;
    uint16_t port_;
    std::atomic<bool> running_{false};

    SocketGuard listen_sock_;
    std::thread accept_thread_;
    std::thread sweep_thread_;
};

} // namespace kvstore
