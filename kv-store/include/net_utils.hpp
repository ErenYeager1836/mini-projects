#pragma once

#include <string>
#include <cstdint>

#ifdef _WIN32
    #ifndef WIN32_LEAN_AND_MEAN
        #define WIN32_LEAN_AND_MEAN
    #endif
    #include <windows.h>
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #pragma comment(lib, "Ws2_32.lib")
#endif

namespace kvstore {

#ifdef _WIN32
using socket_t = SOCKET;
constexpr socket_t INVALID_SOCK = INVALID_SOCKET;
constexpr int SOCK_ERR = SOCKET_ERROR;
#else
using socket_t = int;
constexpr socket_t INVALID_SOCK = -1;
constexpr int SOCK_ERR = -1;
#endif

/**
 * Ensures socket subsystems (such as Winsock2 on Windows) are initialized and cleaned up.
 */
class SocketSubsystem {
public:
    static bool init();
    static void cleanup();
};

/**
 * RAII socket wrapper to automatically close file descriptors and prevent descriptor leaks.
 */
class SocketGuard {
public:
    explicit SocketGuard(socket_t sock = INVALID_SOCK);
    ~SocketGuard();

    SocketGuard(const SocketGuard&) = delete;
    SocketGuard& operator=(const SocketGuard&) = delete;

    SocketGuard(SocketGuard&& other) noexcept;
    SocketGuard& operator=(SocketGuard&& other) noexcept;

    socket_t get() const { return sock_; }
    bool is_valid() const { return sock_ != INVALID_SOCK; }
    void reset(socket_t new_sock = INVALID_SOCK);
    socket_t release();

private:
    socket_t sock_;
};

void close_socket(socket_t s);

} // namespace kvstore
