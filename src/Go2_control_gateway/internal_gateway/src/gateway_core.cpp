#include "go2_gateway/gateway_core.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

namespace go2_gateway {

namespace {

bool is_zero(float value) {
  return std::fabs(value) <= 1e-6F;
}

}  // namespace

GatewayCore::GatewayCore(SportApi& sport_api, Clock clock,
                         GatewayConfig config)
    : sport_api_(sport_api), clock_(std::move(clock)), config_(config) {
  if (!clock_) {
    throw std::invalid_argument("GatewayCore requires a monotonic clock");
  }
  if (config_.watchdog_timeout_sec <= 0.0 ||
      config_.move_update_interval_sec < 0.0 ||
      config_.velocity_change_epsilon < 0.0F || config_.max_vx < 0.0F ||
      config_.max_vy < 0.0F || config_.max_vyaw < 0.0F) {
    throw std::invalid_argument("invalid gateway configuration");
  }
  const int result = sport_api_.StopMove();
  if (result != 0) {
    sdk_code_ = result;
    fault_ = FaultReason::kSdk;
  }
}

std::optional<AckFrame> GatewayCore::handle(const ControlFrame& frame) {
  const double now = clock_();
  if (!std::isfinite(now) || !std::isfinite(frame.vx) ||
      !std::isfinite(frame.vy) || !std::isfinite(frame.vyaw) ||
      frame.session_id == 0 || frame.sequence == 0 ||
      frame.arm_token != 0 || !valid_flags(frame.flags)) {
    return std::nullopt;
  }

  if (active_session_ != 0 && frame.session_id != active_session_) {
    force_locked(FaultReason::kProtocol, 0, moving_);
    active_session_ = frame.session_id;
    last_sequence_ = frame.sequence;
    last_valid_frame_at_ = now;
    has_valid_frame_ = true;
    return make_ack(frame);
  }
  if (active_session_ == 0) {
    active_session_ = frame.session_id;
  }
  if (frame.sequence <= last_sequence_) {
    return std::nullopt;
  }

  last_sequence_ = frame.sequence;
  last_valid_frame_at_ = now;
  has_valid_frame_ = true;
  fault_ = FaultReason::kNone;
  sdk_code_ = 0;
  return process_velocity(frame, now);
}

std::optional<AckFrame> GatewayCore::tick() {
  const int async_sdk_error = sport_api_.PollError();
  if (async_sdk_error != 0) {
    const std::uint64_t session = active_session_;
    const std::uint64_t sequence = last_sequence_;
    force_locked(FaultReason::kSdk, async_sdk_error, true);
    return make_ack(session, sequence, 0);
  }

  if (!moving_ || !has_valid_frame_) {
    return std::nullopt;
  }
  const double now = clock_();
  if (!std::isfinite(now) ||
      now - last_valid_frame_at_ <= config_.watchdog_timeout_sec) {
    return std::nullopt;
  }

  const std::uint64_t session = active_session_;
  const std::uint64_t sequence = last_sequence_;
  force_locked(FaultReason::kWatchdog, 0, true);
  return make_ack(session, sequence, 0);
}

AckFrame GatewayCore::shutdown() {
  force_locked(FaultReason::kShutdown, 0, true);
  return make_ack(active_session_, last_sequence_, 0);
}

std::optional<AckFrame> GatewayCore::process_velocity(
    const ControlFrame& frame, double now) {
  const float vx = std::max(-config_.max_vx,
                            std::min(config_.max_vx, frame.vx));
  const float vy = std::max(-config_.max_vy,
                            std::min(config_.max_vy, frame.vy));
  const float vyaw = std::max(-config_.max_vyaw,
                              std::min(config_.max_vyaw, frame.vyaw));
  const bool has_motion =
      !is_zero(vx) || !is_zero(vy) || !is_zero(vyaw);

  if (!has_motion) {
    if (moving_) {
      const int result = sport_api_.StopMove();
      clear_motion_state();
      if (result != 0) {
        force_locked(FaultReason::kSdk, result, false);
        return make_ack(frame.session_id, frame.sequence, 0);
      }
    }
    sdk_code_ = 0;
    return make_ack(frame);
  }

  const bool velocity_changed =
      !moving_ ||
      std::fabs(vx - applied_vx_) > config_.velocity_change_epsilon ||
      std::fabs(vy - applied_vy_) > config_.velocity_change_epsilon ||
      std::fabs(vyaw - applied_vyaw_) > config_.velocity_change_epsilon;
  if (!velocity_changed) {
    sdk_code_ = 0;
    return make_ack(frame);
  }

  const bool update_due =
      !moving_ ||
      now - last_move_at_ >= config_.move_update_interval_sec;
  if (!update_due) {
    sdk_code_ = 0;
    return make_ack(frame);
  }

  const int result = sport_api_.Move(vx, vy, vyaw);
  if (result != 0) {
    force_locked(FaultReason::kSdk, result, true);
    return make_ack(frame.session_id, frame.sequence, 0);
  }
  moving_ = true;
  last_move_at_ = now;
  applied_vx_ = vx;
  applied_vy_ = vy;
  applied_vyaw_ = vyaw;
  sdk_code_ = 0;
  return make_ack(frame);
}

AckFrame GatewayCore::make_ack(const ControlFrame& frame) const {
  return make_ack(frame.session_id, frame.sequence, 0);
}

AckFrame GatewayCore::make_ack(std::uint64_t session_id,
                               std::uint64_t sequence,
                               std::uint64_t token) const {
  return AckFrame{session_id, sequence, token, state_, sdk_code_, fault_, 0};
}

void GatewayCore::force_locked(FaultReason reason, std::int32_t sdk_code,
                               bool call_stop) {
  if (call_stop) {
    const int stop_result = sport_api_.StopMove();
    if (sdk_code == 0 && stop_result != 0) {
      sdk_code = stop_result;
      reason = FaultReason::kSdk;
    }
  }
  state_ = GatewayState::kLocked;
  fault_ = reason;
  sdk_code_ = sdk_code;
  clear_motion_state();
}

void GatewayCore::clear_motion_state() {
  moving_ = false;
  last_move_at_ = 0.0;
  applied_vx_ = 0.0F;
  applied_vy_ = 0.0F;
  applied_vyaw_ = 0.0F;
}

bool GatewayCore::valid_flags(ControlFlags flags) const {
  return flags == ControlFlags::kNone;
}

}  // namespace go2_gateway
