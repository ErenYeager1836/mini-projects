#include "aof.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>

namespace kvstore {

namespace fs = std::filesystem;

AofLogger::AofLogger(std::string aof_path, AofFsyncPolicy policy)
    : aof_path_(std::move(aof_path)), policy_(policy) {
    if (!aof_path_.empty()) {
        open();
    }
}

AofLogger::~AofLogger() {
    close();
}

bool AofLogger::open() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (aof_path_.empty()) {
        return false;
    }

    file_.open(aof_path_, std::ios::out | std::ios::app | std::ios::binary);
    if (!file_.is_open()) {
        return false;
    }

    if (policy_ == AofFsyncPolicy::EverySec && !running_) {
        running_ = true;
        background_thread_ = std::thread([this]() {
            while (running_) {
                std::this_thread::sleep_for(std::chrono::seconds(1));
                if (running_) {
                    flush();
                }
            }
        });
    }

    return true;
}

void AofLogger::close() {
    if (running_) {
        running_ = false;
        if (background_thread_.joinable()) {
            background_thread_.join();
        }
    }

    std::lock_guard<std::mutex> lock(mutex_);
    if (file_.is_open()) {
        file_.flush();
        file_.close();
    }
}

bool AofLogger::is_open() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return file_.is_open();
}

void AofLogger::flush() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (file_.is_open()) {
        file_.flush();
    }
}

void AofLogger::write_record(const std::string& op, const std::string& key, const std::string& val, int64_t ttl) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!file_.is_open()) return;

    file_ << op << " " << key.size() << " " << val.size() << " " << ttl << "\n";
    if (!key.empty()) {
        file_.write(key.data(), key.size());
    }
    file_ << "\n";
    if (!val.empty()) {
        file_.write(val.data(), val.size());
    }
    file_ << "\n";

    if (policy_ == AofFsyncPolicy::Always) {
        file_.flush();
    }
}

void AofLogger::log_set(const std::string& key, const std::string& value, std::optional<int64_t> ttl) {
    int64_t ttl_val = ttl.value_or(-1);
    write_record("SET", key, value, ttl_val);
}

void AofLogger::log_del(const std::string& key) {
    write_record("DEL", key, "", -1);
}

void AofLogger::log_expire(const std::string& key, int64_t ttl) {
    write_record("EXPIRE", key, "", ttl);
}

std::vector<AofRecord> AofLogger::replay(const std::string& aof_path) {
    std::vector<AofRecord> records;
    if (aof_path.empty() || !fs::exists(aof_path)) {
        return records;
    }

    std::ifstream in(aof_path, std::ios::binary);
    if (!in.is_open()) {
        return records;
    }

    std::string op;
    size_t key_len = 0;
    size_t val_len = 0;
    int64_t ttl = -1;
    std::string dummy;

    while (in >> op >> key_len >> val_len >> ttl) {
        std::getline(in, dummy); // Consume newline

        std::string key(key_len, '\0');
        if (key_len > 0) {
            in.read(&key[0], key_len);
        }
        std::getline(in, dummy);

        std::string val(val_len, '\0');
        if (val_len > 0) {
            in.read(&val[0], val_len);
        }
        std::getline(in, dummy);

        records.push_back({op, std::move(key), std::move(val), ttl});
    }

    return records;
}

} // namespace kvstore
