#pragma once

#include "go2_gateway/protocol.hpp"
#include "go2_gateway/sport_api.hpp"

#include <cstdint>
#include <functional>
#include <optional>

namespace go2_gateway {

struct GatewayConfig {
  double watchdog_timeout_sec{0.5};
  double move_update_interval_sec{0.1};
  float velocity_change_epsilon{1e-3F};
  float max_vx{0.6F};
  float max_vy{0.0F};
  float max_vyaw{1.4F};
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

 private:
  std::optional<AckFrame> process_velocity(const ControlFrame& frame,
                                           double now);
  AckFrame make_ack(const ControlFrame& frame) const;
  AckFrame make_ack(std::uint64_t session_id, std::uint64_t sequence,
                    std::uint64_t token) const;
  void force_locked(FaultReason reason, std::int32_t sdk_code,
                    bool call_stop);
  void clear_motion_state();
  bool valid_flags(ControlFlags flags) const;

  SportApi& sport_api_;
  Clock clock_;
  GatewayConfig config_;
  GatewayState state_{GatewayState::kLocked};
  FaultReason fault_{FaultReason::kNone};
  std::int32_t sdk_code_{0};
  std::uint64_t active_session_{0};
  std::uint64_t last_sequence_{0};
  double last_valid_frame_at_{0.0};
  double last_move_at_{0.0};
  float applied_vx_{0.0F};
  float applied_vy_{0.0F};
  float applied_vyaw_{0.0F};
  bool has_valid_frame_{false};
  bool moving_{false};
};

}  // namespace go2_gateway
