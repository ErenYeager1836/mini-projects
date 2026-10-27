#include "kv_protocol.hpp"
#include "kv_server.hpp"
#include "kv_store.hpp"
#include "net_utils.hpp"

#include <cassert>
#include <chrono>
#include <filesystem>
#include <iostream>
#include <thread>
#include <vector>

namespace fs = std::filesystem;

void test_basic_set_get_del() {
    std::cout << "[+] Running test_basic_set_get_del...\n";
    kvstore::KVStore store;

    // Initially absent
    assert(!store.get("nonexistent").has_value());
    assert(!store.del("nonexistent"));

    // SET and GET
    store.set("user:100", "Alice");
    auto val = store.get("user:100");
    assert(val.has_value());
    assert(val.value() == "Alice");
    assert(store.size() == 1);

    // Overwrite
    store.set("user:100", "Bob");
    assert(store.get("user:100").value() == "Bob");

    // DEL
    assert(store.del("user:100"));
    assert(!store.get("user:100").has_value());
    assert(store.size() == 0);
    std::cout << "    PASSED\n";
}

void test_ttl_and_expiration() {
    std::cout << "[+] Running test_ttl_and_expiration...\n";
    kvstore::KVStore store;

    // Key without expiry has TTL -1
    store.set("permanent", "data");
    assert(store.ttl("permanent") == -1);

    // Key with 1-second expiry
    store.set("ephemeral", "temp_value", 1);
    assert(store.ttl("ephemeral") >= 0);
    assert(store.get("ephemeral").has_value());

    // Wait for expiration
    std::this_thread::sleep_for(std::chrono::milliseconds(1100));

    // Passive expiration on GET
    assert(!store.get("ephemeral").has_value());
    assert(store.ttl("ephemeral") == -2); // Key does not exist

    // EXPIRE command on existing key
    store.set("refreshable", "value");
    assert(store.expire("refreshable", 10));
    assert(store.ttl("refreshable") > 0);
    std::cout << "    PASSED\n";
}

void test_disk_persistence() {
    std::cout << "[+] Running test_disk_persistence...\n";
    std::string test_file = "test_snapshot.kv";
    if (fs::exists(test_file)) {
        fs::remove(test_file);
    }

    {
        kvstore::KVStore store(test_file);
        store.set("alpha", "111");
        store.set("beta", "222");
        store.set("gamma", "333", 60); // 60s TTL
        assert(store.save(test_file));
    }

    // Load from disk into fresh store instance
    {
        kvstore::KVStore reloaded_store(test_file);
        assert(reloaded_store.get("alpha").value() == "111");
        assert(reloaded_store.get("beta").value() == "222");
        assert(reloaded_store.get("gamma").value() == "333");
        assert(reloaded_store.ttl("gamma") > 0);
        assert(reloaded_store.size() == 3);
    }

    if (fs::exists(test_file)) {
        fs::remove(test_file);
    }
    std::cout << "    PASSED\n";
}

void test_protocol_handler() {
    std::cout << "[+] Running test_protocol_handler...\n";
    kvstore::KVStore store;
    bool close_conn = false;

    // PING
    assert(kvstore::ProtocolHandler::execute_command(store, "PING", close_conn) == "+PONG\r\n");
    assert(kvstore::ProtocolHandler::execute_command(store, "PING hello", close_conn) == "+hello\r\n");

    // SET with quotes
    assert(kvstore::ProtocolHandler::execute_command(store, "SET greeting \"hello world\"", close_conn) == "+OK\r\n");
    assert(kvstore::ProtocolHandler::execute_command(store, "GET greeting", close_conn) == "$hello world\r\n");

    // DEL
    assert(kvstore::ProtocolHandler::execute_command(store, "DEL greeting", close_conn) == ":1\r\n");
    assert(kvstore::ProtocolHandler::execute_command(store, "GET greeting", close_conn) == "NIL\r\n");

    // SET with EX
    assert(kvstore::ProtocolHandler::execute_command(store, "SET temp 123 EX 50", close_conn) == "+OK\r\n");
    assert(kvstore::ProtocolHandler::execute_command(store, "TTL temp", close_conn) != ":-1\r\n");

    // QUIT
    assert(kvstore::ProtocolHandler::execute_command(store, "QUIT", close_conn) == "+BYE\r\n");
    assert(close_conn == true);
    (void)close_conn;
    std::cout << "    PASSED\n";
}

void test_concurrent_multithreaded_access() {
    std::cout << "[+] Running test_concurrent_multithreaded_access...\n";
    kvstore::KVStore store;
    constexpr int NUM_THREADS = 8;
    constexpr int OPS_PER_THREAD = 500;

    std::vector<std::thread> workers;
    workers.reserve(NUM_THREADS);

    for (int t = 0; t < NUM_THREADS; ++t) {
        workers.emplace_back([&store, t]() {
            for (int i = 0; i < OPS_PER_THREAD; ++i) {
                std::string k = "key_" + std::to_string(t) + "_" + std::to_string(i);
                std::string v = "val_" + std::to_string(i);
                store.set(k, v);
                auto fetched = store.get(k);
                assert(fetched.has_value() && fetched.value() == v);
            }
        });
    }

    for (auto& w : workers) {
        w.join();
    }

    assert(store.size() == NUM_THREADS * OPS_PER_THREAD);
    std::cout << "    PASSED\n";
}

void test_tcp_server_client_roundtrip() {
    std::cout << "[+] Running test_tcp_server_client_roundtrip...\n";
    kvstore::KVStore store;
    // Bind to port 0 to dynamically assign an available port
    kvstore::KVServer server(store, "127.0.0.1", 0);
    assert(server.start());
    uint16_t port = server.port();
    assert(port > 0);

    // Create client socket and connect
    kvstore::socket_t client_sock = socket(AF_INET, SOCK_STREAM, 0);
    assert(client_sock != kvstore::INVALID_SOCK);
    kvstore::SocketGuard guard(client_sock);

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

    assert(connect(guard.get(), (sockaddr*)&addr, sizeof(addr)) != kvstore::SOCK_ERR);

    auto send_recv = [&](const std::string& msg) -> std::string {
        std::string payload = msg + "\r\n";
        send(guard.get(), payload.data(), static_cast<int>(payload.size()), 0);
        char buf[512];
        int bytes = recv(guard.get(), buf, sizeof(buf) - 1, 0);
        assert(bytes > 0);
        buf[bytes] = '\0';
        return std::string(buf);
    };

    assert(send_recv("PING") == "+PONG\r\n");
    assert(send_recv("SET key1 val1") == "+OK\r\n");
    assert(send_recv("GET key1") == "$val1\r\n");
    assert(send_recv("DEL key1") == ":1\r\n");
    assert(send_recv("GET key1") == "NIL\r\n");
    assert(send_recv("QUIT") == "+BYE\r\n");

    guard.reset();
    server.stop();
    std::cout << "    PASSED\n";
}

int main() {
    std::cout << "=== Running kv-store test suite ===\n";
    kvstore::SocketSubsystem::init();

    test_basic_set_get_del();
    test_ttl_and_expiration();
    test_disk_persistence();
    test_protocol_handler();
    test_concurrent_multithreaded_access();
    test_tcp_server_client_roundtrip();

    kvstore::SocketSubsystem::cleanup();
    std::cout << "=== All 6 kv-store tests passed successfully! ===\n";
    return 0;
}
