#include "go2_gateway/gateway_core.hpp"
#include "go2_gateway/protocol.hpp"
#include "go2_gateway/sport_api.hpp"

#include <arpa/inet.h>
#include <poll.h>
#include <signal.h>
#include <sys/socket.h>
#include <unistd.h>

#include <array>
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

#ifndef GO2_GATEWAY_HAS_UNITREE_SDK
#define GO2_GATEWAY_HAS_UNITREE_SDK 0
#endif

namespace {

volatile sig_atomic_t g_stop_requested = 0;

void signal_handler(int) {
  g_stop_requested = 1;
}

struct Options {
  std::string bind_ip{"192.168.123.18"};
  std::uint16_t port{15000};
  std::string allowed_ip{"192.168.123.5"};
  std::string interface_name{"eth0"};
  bool dry_run{false};
};

std::string require_value(int argc, char** argv, int& index) {
  if (index + 1 >= argc) {
    throw std::invalid_argument(std::string("missing value for ") + argv[index]);
  }
  ++index;
  return argv[index];
}

Options parse_options(int argc, char** argv) {
  Options options;
  for (int index = 1; index < argc; ++index) {
    const std::string argument = argv[index];
    if (argument == "--dry-run") {
      options.dry_run = true;
    } else if (argument == "--bind") {
      options.bind_ip = require_value(argc, argv, index);
    } else if (argument == "--port") {
      const int port = std::stoi(require_value(argc, argv, index));
      if (port < 1 || port > 65535) {
        throw std::invalid_argument("port must be in [1, 65535]");
      }
      options.port = static_cast<std::uint16_t>(port);
    } else if (argument == "--allowed-ip") {
      options.allowed_ip = require_value(argc, argv, index);
    } else if (argument == "--interface") {
      options.interface_name = require_value(argc, argv, index);
    } else if (argument == "--help") {
      std::cout
          << "Usage: go2_cmd_gateway [--dry-run] [--bind IP] [--port PORT] "
             "[--allowed-ip IP] [--interface NAME]\n";
      std::exit(0);
    } else {
      throw std::invalid_argument("unknown argument: " + argument);
    }
  }
  return options;
}

sockaddr_in make_address(const std::string& ip, std::uint16_t port) {
  sockaddr_in address{};
  address.sin_family = AF_INET;
  address.sin_port = htons(port);
  if (inet_pton(AF_INET, ip.c_str(), &address.sin_addr) != 1) {
    throw std::invalid_argument("invalid IPv4 address: " + ip);
  }
  return address;
}

double monotonic_seconds() {
  using Clock = std::chrono::steady_clock;
  return std::chrono::duration<double>(Clock::now().time_since_epoch()).count();
}

bool same_ip(const sockaddr_in& left, const sockaddr_in& right) {
  return left.sin_family == AF_INET &&
         left.sin_addr.s_addr == right.sin_addr.s_addr;
}

bool send_ack(int socket_fd, const sockaddr_in& destination,
              const go2_gateway::AckFrame& ack) {
  const auto payload = go2_gateway::encode_ack(ack);
  const auto sent =
      sendto(socket_fd, payload.data(), payload.size(), 0,
             reinterpret_cast<const sockaddr*>(&destination),
             sizeof(destination));
  return sent == static_cast<ssize_t>(payload.size());
}

}  // namespace

int main(int argc, char** argv) {
  int socket_fd = -1;
  try {
    const Options options = parse_options(argc, argv);
    std::unique_ptr<go2_gateway::SportApi> sport_api;
    if (options.dry_run) {
      sport_api = go2_gateway::make_dry_run_sport_api();
    } else {
#if GO2_GATEWAY_HAS_UNITREE_SDK
      sport_api =
          go2_gateway::make_unitree_sport_api(options.interface_name);
#else
      throw std::runtime_error(
          "this binary has no Unitree SDK support; pass --dry-run");
#endif
    }

    go2_gateway::GatewayCore core(*sport_api, monotonic_seconds);
    socket_fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (socket_fd < 0) {
      throw std::runtime_error(std::string("socket: ") + std::strerror(errno));
    }
    const int reuse = 1;
    setsockopt(socket_fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    const sockaddr_in bind_address =
        make_address(options.bind_ip, options.port);
    if (bind(socket_fd, reinterpret_cast<const sockaddr*>(&bind_address),
             sizeof(bind_address)) != 0) {
      throw std::runtime_error(std::string("bind: ") + std::strerror(errno));
    }
    const sockaddr_in allowed_address = make_address(options.allowed_ip, 0);

    ::signal(SIGINT, signal_handler);
    ::signal(SIGTERM, signal_handler);
    std::cout << "READY bind=" << options.bind_ip << ':' << options.port
              << " allowed=" << options.allowed_ip
              << " interface=" << options.interface_name
              << " mode=" << (options.dry_run ? "dry-run" : "unitree")
              << std::endl;

    sockaddr_in last_peer{};
    bool has_last_peer = false;
    std::array<std::uint8_t, 2048> buffer{};
    while (!g_stop_requested) {
      pollfd descriptor{socket_fd, POLLIN, 0};
      const int poll_result = poll(&descriptor, 1, 10);
      if (poll_result < 0 && errno != EINTR) {
        throw std::runtime_error(std::string("poll: ") + std::strerror(errno));
      }
      if (poll_result > 0 && (descriptor.revents & POLLIN) != 0) {
        sockaddr_in source{};
        socklen_t source_size = sizeof(source);
        const ssize_t received =
            recvfrom(socket_fd, buffer.data(), buffer.size(), 0,
                     reinterpret_cast<sockaddr*>(&source), &source_size);
        if (received > 0 && same_ip(source, allowed_address)) {
          go2_gateway::ControlFrame frame{};
          std::string error;
          if (go2_gateway::decode_control(
                  buffer.data(), static_cast<std::size_t>(received), frame,
                  &error)) {
            const auto ack = core.handle(frame);
            if (ack) {
              last_peer = source;
              has_last_peer = true;
              send_ack(socket_fd, source, *ack);
            }
          }
        }
      }

      const auto timeout_ack = core.tick();
      if (timeout_ack && has_last_peer) {
        send_ack(socket_fd, last_peer, *timeout_ack);
      }
    }

    const auto shutdown_ack = core.shutdown();
    if (has_last_peer) {
      send_ack(socket_fd, last_peer, shutdown_ack);
    }
    close(socket_fd);
    return 0;
  } catch (const std::exception& error) {
    if (socket_fd >= 0) {
      close(socket_fd);
    }
    std::cerr << "go2_cmd_gateway: " << error.what() << '\n';
    return 1;
  }
}
