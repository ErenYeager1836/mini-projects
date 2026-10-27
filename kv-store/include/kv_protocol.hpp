#pragma once

#include "kv_store.hpp"
#include <string>
#include <vector>

namespace kvstore {

/**
 * Parses raw text protocol lines and executes operations against the KVStore.
 */
class ProtocolHandler {
public:
    static std::vector<std::string> parse_command_line(const std::string& line);
    static std::string execute_command(KVStore& store, const std::string& line, bool& should_close);
};

} // namespace kvstore
