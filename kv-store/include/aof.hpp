#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace kvstore {

enum class AofFsyncPolicy {
    Always,    // Flush/fsync after every write operation (maximum durability)
    EverySec,  // Background thread flushes every 1 second (Redis default)
    No         // Leave flushing to OS buffer cache (maximum performance)
};

struct AofRecord {
    std::string op; // "SET", "DEL", "EXPIRE"
    std::string key;
    std::string value;
    int64_t ttl = -1;
};

/**
 * Append-Only File (AOF) logger tracking write operations (SET, DEL, EXPIRE) to disk.
 * Supports configurable fsync policies and deterministic crash-recovery replay.
 */
class AofLogger {
public:
    explicit AofLogger(std::string aof_path, AofFsyncPolicy policy = AofFsyncPolicy::Always);
    ~AofLogger();

    bool open();
    void close();
    bool is_open() const;

    void log_set(const std::string& key, const std::string& value, std::optional<int64_t> ttl = std::nullopt);
    void log_del(const std::string& key);
    void log_expire(const std::string& key, int64_t ttl);

    void flush();

    // Static helper to parse and replay an entire AOF log from disk
    static std::vector<AofRecord> replay(const std::string& aof_path);

private:
    void write_record(const std::string& op, const std::string& key, const std::string& val, int64_t ttl);

    std::string aof_path_;
    AofFsyncPolicy policy_;
    std::ofstream file_;
    mutable std::mutex mutex_;
    std::atomic<bool> running_{false};
    std::thread background_thread_;
};

} // namespace kvstore
