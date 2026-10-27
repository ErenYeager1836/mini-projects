#include "kv_protocol.hpp"

#include <algorithm>
#include <cctype>
#include <sstream>

namespace kvstore {

static std::string to_upper(std::string s) {
    for (char& c : s) {
        c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    }
    return s;
}

std::vector<std::string> ProtocolHandler::parse_command_line(const std::string& line) {
    std::vector<std::string> tokens;
    std::string current;
    bool in_quotes = false;
    char quote_char = '\0';

    for (size_t i = 0; i < line.size(); ++i) {
        char c = line[i];

        if (c == '\r' || c == '\n') {
            continue;
        }

        if (in_quotes) {
            if (c == quote_char) {
                in_quotes = false;
            } else if (c == '\\' && (i + 1 < line.size()) && line[i + 1] == quote_char) {
                current += quote_char;
                ++i;
            } else {
                current += c;
            }
        } else {
            if (c == '"' || c == '\'') {
                in_quotes = true;
                quote_char = c;
            } else if (std::isspace(static_cast<unsigned char>(c))) {
                if (!current.empty()) {
                    tokens.push_back(current);
                    current.clear();
                }
            } else {
                current += c;
            }
        }
    }

    if (!current.empty()) {
        tokens.push_back(current);
    }

    return tokens;
}

std::string ProtocolHandler::execute_command(KVStore& store, const std::string& line, bool& should_close) {
    should_close = false;
    auto tokens = parse_command_line(line);
    if (tokens.empty()) {
        return "";
    }

    std::string cmd = to_upper(tokens[0]);

    if (cmd == "PING") {
        if (tokens.size() > 1) {
            return "+" + tokens[1] + "\r\n";
        }
        return "+PONG\r\n";
    }

    if (cmd == "QUIT") {
        should_close = true;
        return "+BYE\r\n";
    }

    if (cmd == "SET") {
        if (tokens.size() < 3) {
            return "-ERR wrong number of arguments for 'set' command\r\n";
        }
        const std::string& key = tokens[1];
        const std::string& value = tokens[2];
        std::optional<int64_t> ttl = std::nullopt;

        // Check for optional EX <seconds>
        if (tokens.size() >= 5) {
            if (to_upper(tokens[3]) == "EX") {
                try {
                    ttl = std::stoll(tokens[4]);
                } catch (...) {
                    return "-ERR value is not an integer or out of range\r\n";
                }
            } else {
                return "-ERR syntax error\r\n";
            }
        }
        store.set(key, value, ttl);
        return "+OK\r\n";
    }

    if (cmd == "GET") {
        if (tokens.size() != 2) {
            return "-ERR wrong number of arguments for 'get' command\r\n";
        }
        auto val = store.get(tokens[1]);
        if (!val.has_value()) {
            return "NIL\r\n";
        }
        return "$" + val.value() + "\r\n";
    }

    if (cmd == "DEL") {
        if (tokens.size() != 2) {
            return "-ERR wrong number of arguments for 'del' command\r\n";
        }
        bool deleted = store.del(tokens[1]);
        return ":" + std::to_string(deleted ? 1 : 0) + "\r\n";
    }

    if (cmd == "EXPIRE") {
        if (tokens.size() != 3) {
            return "-ERR wrong number of arguments for 'expire' command\r\n";
        }
        int64_t secs = 0;
        try {
            secs = std::stoll(tokens[2]);
        } catch (...) {
            return "-ERR value is not an integer or out of range\r\n";
        }
        bool res = store.expire(tokens[1], secs);
        return ":" + std::to_string(res ? 1 : 0) + "\r\n";
    }

    if (cmd == "TTL") {
        if (tokens.size() != 2) {
            return "-ERR wrong number of arguments for 'ttl' command\r\n";
        }
        int64_t remaining = store.ttl(tokens[1]);
        return ":" + std::to_string(remaining) + "\r\n";
    }

    if (cmd == "KEYS") {
        auto key_list = store.keys();
        std::ostringstream oss;
        oss << "*" << key_list.size() << "\r\n";
        for (const auto& k : key_list) {
            oss << "$" << k.size() << "\r\n" << k << "\r\n";
        }
        return oss.str();
    }

    if (cmd == "SAVE") {
        bool ok = store.save();
        if (ok) {
            return "+OK\r\n";
        }
        return "-ERR failed to save snapshot to disk\r\n";
    }

    return "-ERR unknown command '" + tokens[0] + "'\r\n";
}

} // namespace kvstore
