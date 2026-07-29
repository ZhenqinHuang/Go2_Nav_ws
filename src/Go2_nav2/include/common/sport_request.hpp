#ifndef GO2_NAV2_COMMON_SPORT_REQUEST_HPP_
#define GO2_NAV2_COMMON_SPORT_REQUEST_HPP_

#include <atomic>
#include <chrono>
#include <cstdint>

#include "unitree_api/msg/request.hpp"

namespace go2_nav2 {

inline std::uint64_t next_sport_request_id() {
  static std::atomic<std::uint64_t> next_id{
      static_cast<std::uint64_t>(
          std::chrono::steady_clock::now().time_since_epoch().count()) |
      1ULL};
  return next_id.fetch_add(1, std::memory_order_relaxed);
}

inline void prepare_sport_request(unitree_api::msg::Request& request,
                                  std::int32_t api_id) {
  request.header.identity.id = next_sport_request_id();
  request.header.identity.api_id = api_id;
  request.header.lease.id = 0;
  request.header.policy.priority = 0;
  request.header.policy.noreply = true;
}

}  // namespace go2_nav2

#endif  // GO2_NAV2_COMMON_SPORT_REQUEST_HPP_
