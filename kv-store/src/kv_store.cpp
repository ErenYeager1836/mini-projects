#include "kv_store.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <mutex>

namespace kvstore {

namespace fs = std::filesystem;

KVStore::KVStore(std::string persistence_file)
    : persistence_file_(std::move(persistence_file)) {
    if (!persistence_file_.empty() && fs::exists(persistence_file_)) {
        load(persistence_file_);
    }
}

KVStore::~KVStore() = default;

void KVStore::set(const std::string& key, const std::string& value, std::optional<int64_t> ttl_seconds) {
    std::unique_lock<std::shared_mutex> lock(mutex_);
    auto now = std::chrono::steady_clock::now();

    Entry entry;
    entry.value = value;
    if (ttl_seconds.has_value() && ttl_seconds.value() > 0) {
        entry.expires_at = now + std::chrono::seconds(ttl_seconds.value());
    } else {
        entry.expires_at = std::nullopt;
    }

    table_[key] = std::move(entry);
}

std::optional<std::string> KVStore::get(const std::string& key) {
    auto now = std::chrono::steady_clock::now();

    // First attempt quick lookup under shared_lock
    {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        auto it = table_.find(key);
        if (it == table_.end()) {
            return std::nullopt;
        }
        if (!it->second.is_expired(now)) {
            return it->second.value;
        }
    }

    // Lazy deletion of expired key requires unique_lock
    std::unique_lock<std::shared_mutex> lock(mutex_);
    auto it = table_.find(key);
    if (it != table_.end() && it->second.is_expired(now)) {
        table_.erase(it);
        return std::nullopt;
    }
    if (it != table_.end()) {
        return it->second.value;
    }
    return std::nullopt;
}

bool KVStore::del(const std::string& key) {
    std::unique_lock<std::shared_mutex> lock(mutex_);
    auto it = table_.find(key);
    if (it == table_.end()) {
        return false;
    }
    auto now = std::chrono::steady_clock::now();
    bool expired = it->second.is_expired(now);
    table_.erase(it);
    return !expired;
}

bool KVStore::expire(const std::string& key, int64_t ttl_seconds) {
    std::unique_lock<std::shared_mutex> lock(mutex_);
    auto it = table_.find(key);
    if (it == table_.end()) {
        return false;
    }
    auto now = std::chrono::steady_clock::now();
    if (it->second.is_expired(now)) {
        table_.erase(it);
        return false;
    }

    if (ttl_seconds > 0) {
        it->second.expires_at = now + std::chrono::seconds(ttl_seconds);
    } else {
        // Immediate expiration
        table_.erase(it);
    }
    return true;
}

int64_t KVStore::ttl(const std::string& key) {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    auto it = table_.find(key);
    if (it == table_.end()) {
        return -2; // Key does not exist
    }
    auto now = std::chrono::steady_clock::now();
    if (it->second.is_expired(now)) {
        return -2;
    }
    if (!it->second.expires_at.has_value()) {
        return -1; // Key exists without expiration
    }

    auto remaining = std::chrono::duration_cast<std::chrono::seconds>(it->second.expires_at.value() - now).count();
    return (remaining >= 0) ? remaining : -2;
}

std::vector<std::string> KVStore::keys() {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    auto now = std::chrono::steady_clock::now();
    std::vector<std::string> result;
    result.reserve(table_.size());

    for (const auto& [k, entry] : table_) {
        if (!entry.is_expired(now)) {
            result.push_back(k);
        }
    }
    return result;
}

size_t KVStore::size() {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    auto now = std::chrono::steady_clock::now();
    size_t count = 0;
    for (const auto& [k, entry] : table_) {
        if (!entry.is_expired(now)) {
            ++count;
        }
    }
    return count;
}

void KVStore::clear() {
    std::unique_lock<std::shared_mutex> lock(mutex_);
    table_.clear();
}

size_t KVStore::cleanup_expired() {
    std::unique_lock<std::shared_mutex> lock(mutex_);
    auto now = std::chrono::steady_clock::now();
    size_t purged = 0;

    for (auto it = table_.begin(); it != table_.end(); ) {
        if (it->second.is_expired(now)) {
            it = table_.erase(it);
            ++purged;
        } else {
            ++it;
        }
    }
    return purged;
}

bool KVStore::save(const std::string& filename) {
    std::string target = filename.empty() ? persistence_file_ : filename;
    if (target.empty()) {
        return false;
    }

    std::string tmp_file = target + ".tmp";

    // Copy snapshot while holding read lock
    struct SnapshotItem {
        std::string key;
        std::string val;
        int64_t ttl_secs;
    };
    std::vector<SnapshotItem> items;
    {
        std::shared_lock<std::shared_mutex> lock(mutex_);
        auto now = std::chrono::steady_clock::now();
        items.reserve(table_.size());
        for (const auto& [k, entry] : table_) {
            if (!entry.is_expired(now)) {
                int64_t remaining_ttl = -1;
                if (entry.expires_at.has_value()) {
                    auto diff = std::chrono::duration_cast<std::chrono::seconds>(entry.expires_at.value() - now).count();
                    remaining_ttl = (diff > 0) ? diff : 0;
                }
                items.push_back({k, entry.value, remaining_ttl});
            }
        }
    }

    // Write snapshot to disk without holding table lock
    std::ofstream out(tmp_file, std::ios::binary);
    if (!out.is_open()) {
        return false;
    }

    out << "KVSTORE_V1\n";
    out << items.size() << "\n";
    for (const auto& item : items) {
        out << item.key.size() << " " << item.val.size() << " " << item.ttl_secs << "\n";
        out.write(item.key.data(), item.key.size());
        out << "\n";
        out.write(item.val.data(), item.val.size());
        out << "\n";
    }
    out.close();

    // Atomic filesystem swap
    std::error_code ec;
    fs::rename(tmp_file, target, ec);
    return !ec;
}

bool KVStore::load(const std::string& filename) {
    std::string target = filename.empty() ? persistence_file_ : filename;
    if (target.empty() || !fs::exists(target)) {
        return false;
    }

    std::ifstream in(target, std::ios::binary);
    if (!in.is_open()) {
        return false;
    }

    std::string header;
    if (!std::getline(in, header) || header != "KVSTORE_V1") {
        return false;
    }

    size_t count = 0;
    if (!(in >> count)) {
        return false;
    }

    std::string dummy;
    std::getline(in, dummy); // consume newline

    std::unique_lock<std::shared_mutex> lock(mutex_);
    table_.clear();
    auto now = std::chrono::steady_clock::now();

    for (size_t i = 0; i < count; ++i) {
        size_t k_len = 0, v_len = 0;
        int64_t ttl_secs = -1;
        if (!(in >> k_len >> v_len >> ttl_secs)) {
            break;
        }
        std::getline(in, dummy); // newline

        std::string k(k_len, '\0');
        in.read(&k[0], k_len);
        std::getline(in, dummy);

        std::string v(v_len, '\0');
        in.read(&v[0], v_len);
        std::getline(in, dummy);

        Entry entry;
        entry.value = std::move(v);
        if (ttl_secs > 0) {
            entry.expires_at = now + std::chrono::seconds(ttl_secs);
        } else {
            entry.expires_at = std::nullopt;
        }
        table_[std::move(k)] = std::move(entry);
    }

    return true;
}

} // namespace kvstore
