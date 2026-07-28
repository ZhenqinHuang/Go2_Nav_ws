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
  if (config_.arming_settle_sec < 0.0 ||
      config_.watchdog_timeout_sec <= 0.0 || config_.max_vx < 0.0F ||
      config_.max_vy < 0.0F || config_.max_vyaw < 0.0F ||
      config_.revoked_token_limit == 0) {
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
      !valid_flags(frame.flags)) {
    return std::nullopt;
  }

  if (active_session_ != 0 && frame.session_id != active_session_) {
    if (state_ != GatewayState::kLocked) {
      force_locked(FaultReason::kProtocol, 0, true);
    }
    active_session_ = frame.session_id;
    last_sequence_ = frame.sequence;
    last_valid_frame_at_ = now;
    has_valid_frame_ = true;
    fault_ = FaultReason::kProtocol;
    return make_ack(frame.session_id, frame.sequence, frame.arm_token);
  }
  if (active_session_ == 0) {
    active_session_ = frame.session_id;
  }
  if (frame.sequence <= last_sequence_) {
    return std::nullopt;
  }

  if (frame.flags == ControlFlags::kDisarm) {
    last_sequence_ = frame.sequence;
    last_valid_frame_at_ = now;
    has_valid_frame_ = true;
    const std::uint64_t reply_token = frame.arm_token;
    const int result = sport_api_.StopMove();
    if (arm_token_ != 0) {
      revoke(arm_token_);
    }
    state_ = GatewayState::kLocked;
    arm_token_ = 0;
    moving_ = false;
    sdk_code_ = result;
    fault_ =
        result == 0 ? FaultReason::kExplicitDisarm : FaultReason::kSdk;
    return make_ack(frame.session_id, frame.sequence, reply_token);
  }

  if (state_ == GatewayState::kLocked) {
    if (frame.flags == ControlFlags::kNone && frame.arm_token == 0) {
      last_sequence_ = frame.sequence;
      last_valid_frame_at_ = now;
      has_valid_frame_ = true;
      return make_ack(frame);
    }
    if (frame.flags != ControlFlags::kArmRequest || frame.arm_token == 0 ||
        is_token_revoked(frame.arm_token)) {
      return std::nullopt;
    }

    last_sequence_ = frame.sequence;
    last_valid_frame_at_ = now;
    has_valid_frame_ = true;
    arm_token_ = frame.arm_token;
    sdk_code_ = sport_api_.BalanceStand();
    if (sdk_code_ != 0) {
      const std::uint64_t reply_token = arm_token_;
      force_locked(FaultReason::kSdk, sdk_code_, true);
      return make_ack(frame.session_id, frame.sequence, reply_token);
    }
    state_ = GatewayState::kArming;
    fault_ = FaultReason::kNone;
    arming_started_at_ = now;
    moving_ = false;
    return make_ack(frame);
  }

  if (frame.arm_token != arm_token_) {
    return std::nullopt;
  }
  if (frame.flags != ControlFlags::kNone &&
      frame.flags != ControlFlags::kArmRequest) {
    return std::nullopt;
  }

  last_sequence_ = frame.sequence;
  last_valid_frame_at_ = now;
  has_valid_frame_ = true;
  if (state_ == GatewayState::kArming &&
      now - arming_started_at_ >= config_.arming_settle_sec) {
    state_ = GatewayState::kArmed;
  }
  if (state_ == GatewayState::kArming ||
      frame.flags == ControlFlags::kArmRequest) {
    return make_ack(frame);
  }
  return process_velocity(frame);
}

std::optional<AckFrame> GatewayCore::tick() {
  if ((state_ != GatewayState::kArming &&
       state_ != GatewayState::kArmed) ||
      !has_valid_frame_) {
    return std::nullopt;
  }
  const double now = clock_();
  if (!std::isfinite(now) ||
      now - last_valid_frame_at_ <= config_.watchdog_timeout_sec) {
    return std::nullopt;
  }

  const std::uint64_t session = active_session_;
  const std::uint64_t sequence = last_sequence_;
  const std::uint64_t token = arm_token_;
  force_locked(FaultReason::kWatchdog, 0, true);
  return make_ack(session, sequence, token);
}

AckFrame GatewayCore::shutdown() {
  const std::uint64_t token = arm_token_;
  force_locked(FaultReason::kShutdown, 0, true);
  return make_ack(active_session_, last_sequence_, token);
}

bool GatewayCore::is_token_revoked(std::uint64_t token) const {
  return token != 0 && revoked_tokens_.count(token) != 0;
}

std::optional<AckFrame> GatewayCore::process_velocity(
    const ControlFrame& frame) {
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
      moving_ = false;
      if (result != 0) {
        const std::uint64_t reply_token = arm_token_;
        force_locked(FaultReason::kSdk, result, false);
        return make_ack(frame.session_id, frame.sequence, reply_token);
      }
    }
    sdk_code_ = 0;
    return make_ack(frame);
  }

  const int result = sport_api_.Move(vx, vy, vyaw);
  if (result != 0) {
    const std::uint64_t reply_token = arm_token_;
    force_locked(FaultReason::kSdk, result, true);
    return make_ack(frame.session_id, frame.sequence, reply_token);
  }
  moving_ = true;
  sdk_code_ = 0;
  return make_ack(frame);
}

AckFrame GatewayCore::make_ack(const ControlFrame& frame) const {
  return make_ack(frame.session_id, frame.sequence, frame.arm_token);
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
  if (arm_token_ != 0) {
    revoke(arm_token_);
  }
  state_ = GatewayState::kLocked;
  fault_ = reason;
  sdk_code_ = sdk_code;
  arm_token_ = 0;
  moving_ = false;
}

void GatewayCore::revoke(std::uint64_t token) {
  if (token == 0 || revoked_tokens_.count(token) != 0) {
    return;
  }
  revoked_tokens_.insert(token);
  revoked_order_.push_back(token);
  while (revoked_order_.size() > config_.revoked_token_limit) {
    revoked_tokens_.erase(revoked_order_.front());
    revoked_order_.pop_front();
  }
}

bool GatewayCore::valid_flags(ControlFlags flags) const {
  return flags == ControlFlags::kNone ||
         flags == ControlFlags::kArmRequest ||
         flags == ControlFlags::kDisarm;
}

}  // namespace go2_gateway
