#pragma once

#include "aof.hpp"

#include <chrono>
#include <cstdint>
#include <memory>
#include <optional>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace kvstore {

/**
 * Value container storing raw string payload and optional steady-clock expiration timestamp.
 */
struct Entry {
    std::string value;
    std::optional<std::chrono::steady_clock::time_point> expires_at;

    bool is_expired(std::chrono::steady_clock::time_point now) const {
        return expires_at.has_value() && (now >= expires_at.value());
    }
};

/**
 * Thread-safe In-Memory Key-Value Storage Engine with TTL expiration, snapshots, and AOF logging.
 */
class KVStore {
public:
    explicit KVStore(std::string persistence_file = "", std::string aof_file = "", AofFsyncPolicy aof_policy = AofFsyncPolicy::Always);
    ~KVStore();

    // Core operations
    void set(const std::string& key, const std::string& value, std::optional<int64_t> ttl_seconds = std::nullopt);
    std::optional<std::string> get(const std::string& key);
    bool del(const std::string& key);
    bool expire(const std::string& key, int64_t ttl_seconds);
    int64_t ttl(const std::string& key);
    std::vector<std::string> keys();
    size_t size();
    void clear();

    // Persistence
    bool save(const std::string& filename = "");
    bool load(const std::string& filename = "");

    // Append-Only File (AOF)
    void enable_aof(const std::string& aof_file, AofFsyncPolicy policy = AofFsyncPolicy::Always);
    bool replay_aof(const std::string& aof_file);

    // Expiry sweep
    size_t cleanup_expired();

private:
    mutable std::shared_mutex mutex_;
    std::unordered_map<std::string, Entry> table_;
    std::string persistence_file_;
    std::string aof_file_;
    std::unique_ptr<AofLogger> aof_;

    // Internal helper called while holding a lock
    bool is_expired_locked(const std::string& key, std::chrono::steady_clock::time_point now) const;
};

} // namespace kvstore
