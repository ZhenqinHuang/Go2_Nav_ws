#pragma once

#include "go2_gateway/protocol.hpp"
#include "go2_gateway/sport_api.hpp"

#include <cstdint>
#include <deque>
#include <functional>
#include <optional>
#include <unordered_set>

namespace go2_gateway {

struct GatewayConfig {
  double arming_settle_sec{0.8};
  double watchdog_timeout_sec{0.5};
  float max_vx{0.6F};
  float max_vy{0.0F};
  float max_vyaw{1.4F};
  std::size_t revoked_token_limit{256};
};

class GatewayCore {
 public:
  using Clock = std::function<double()>;

  GatewayCore(SportApi& sport_api, Clock clock,
              GatewayConfig config = GatewayConfig{});

  std::optional<AckFrame> handle(const ControlFrame& frame);
  std::optional<AckFrame> tick();
  AckFrame shutdown();

  GatewayState state() const { return state_; }
  bool is_token_revoked(std::uint64_t token) const;

 private:
  std::optional<AckFrame> process_velocity(const ControlFrame& frame);
  AckFrame make_ack(const ControlFrame& frame) const;
  AckFrame make_ack(std::uint64_t session_id, std::uint64_t sequence,
                    std::uint64_t token) const;
  void force_locked(FaultReason reason, std::int32_t sdk_code,
                    bool call_stop);
  void revoke(std::uint64_t token);
  bool valid_flags(ControlFlags flags) const;

  SportApi& sport_api_;
  Clock clock_;
  GatewayConfig config_;
  GatewayState state_{GatewayState::kLocked};
  FaultReason fault_{FaultReason::kNone};
  std::int32_t sdk_code_{0};
  std::uint64_t active_session_{0};
  std::uint64_t last_sequence_{0};
  std::uint64_t arm_token_{0};
  double arming_started_at_{0.0};
  double last_valid_frame_at_{0.0};
  bool has_valid_frame_{false};
  bool moving_{false};
  std::deque<std::uint64_t> revoked_order_;
  std::unordered_set<std::uint64_t> revoked_tokens_;
};

}  // namespace go2_gateway
