#pragma once

#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

namespace go2_gateway {

constexpr std::uint32_t kMagic = 0x47324757U;
constexpr std::uint16_t kVersion = 1;
constexpr std::uint16_t kControlPacketType = 1;
constexpr std::uint16_t kAckPacketType = 2;
constexpr std::size_t kControlFrameSize = 56;
constexpr std::size_t kAckFrameSize = 56;

enum class ControlFlags : std::uint32_t {
  kNone = 0,
  kArmRequest = 1U << 0,
  kDisarm = 1U << 1,
  kEmergencyStop = 1U << 2,
  kResetEstop = 1U << 3,
  kStand = 1U << 4,
  kLie = 1U << 5,
};

constexpr std::uint32_t kAckEstopLatched = 1U << 0;
constexpr std::uint32_t kAckCommandAccepted = 1U << 1;
constexpr std::uint32_t kAckPostureStanding = 1U << 2;
constexpr std::uint32_t kAckPostureLying = 1U << 3;

enum class GatewayState : std::uint32_t {
  kLocked = 0,
  kArming = 1,
  kArmed = 2,
  kFault = 3,
};

enum class FaultReason : std::uint32_t {
  kNone = 0,
  kWatchdog = 1,
  kProtocol = 2,
  kSdk = 3,
  kExplicitDisarm = 4,
  kShutdown = 5,
  kEstop = 6,
};

struct ControlFrame {
  std::uint64_t session_id{0};
  std::uint64_t sequence{0};
  std::uint64_t arm_token{0};
  ControlFlags flags{ControlFlags::kNone};
  float vx{0.0F};
  float vy{0.0F};
  float vyaw{0.0F};
};

struct AckFrame {
  std::uint64_t session_id{0};
  std::uint64_t sequence{0};
  std::uint64_t arm_token{0};
  GatewayState state{GatewayState::kLocked};
  std::int32_t sdk_code{0};
  FaultReason fault{FaultReason::kNone};
  std::uint32_t flags{0};
};

namespace detail {

inline void set_error(std::string* error, const char* message) {
  if (error != nullptr) {
    *error = message;
  }
}

inline std::uint16_t read_u16(const std::uint8_t* data) {
  return static_cast<std::uint16_t>(
      (static_cast<std::uint16_t>(data[0]) << 8U) |
      static_cast<std::uint16_t>(data[1]));
}

inline std::uint32_t read_u32(const std::uint8_t* data) {
  return (static_cast<std::uint32_t>(data[0]) << 24U) |
         (static_cast<std::uint32_t>(data[1]) << 16U) |
         (static_cast<std::uint32_t>(data[2]) << 8U) |
         static_cast<std::uint32_t>(data[3]);
}

inline std::uint64_t read_u64(const std::uint8_t* data) {
  std::uint64_t result = 0;
  for (int index = 0; index < 8; ++index) {
    result = (result << 8U) | static_cast<std::uint64_t>(data[index]);
  }
  return result;
}

inline float read_float(const std::uint8_t* data) {
  const std::uint32_t bits = read_u32(data);
  float value = 0.0F;
  static_assert(sizeof(value) == sizeof(bits), "float32 is required");
  std::memcpy(&value, &bits, sizeof(value));
  return value;
}

inline std::int32_t read_i32(const std::uint8_t* data) {
  const std::uint32_t bits = read_u32(data);
  std::int32_t value = 0;
  std::memcpy(&value, &bits, sizeof(value));
  return value;
}

inline void append_u16(std::vector<std::uint8_t>& output,
                       std::uint16_t value) {
  output.push_back(static_cast<std::uint8_t>((value >> 8U) & 0xFFU));
  output.push_back(static_cast<std::uint8_t>(value & 0xFFU));
}

inline void append_u32(std::vector<std::uint8_t>& output,
                       std::uint32_t value) {
  output.push_back(static_cast<std::uint8_t>((value >> 24U) & 0xFFU));
  output.push_back(static_cast<std::uint8_t>((value >> 16U) & 0xFFU));
  output.push_back(static_cast<std::uint8_t>((value >> 8U) & 0xFFU));
  output.push_back(static_cast<std::uint8_t>(value & 0xFFU));
}

inline void append_u64(std::vector<std::uint8_t>& output,
                       std::uint64_t value) {
  for (int shift = 56; shift >= 0; shift -= 8) {
    output.push_back(
        static_cast<std::uint8_t>((value >> static_cast<unsigned>(shift)) &
                                  0xFFU));
  }
}

inline void append_float(std::vector<std::uint8_t>& output, float value) {
  std::uint32_t bits = 0;
  std::memcpy(&bits, &value, sizeof(bits));
  append_u32(output, bits);
}

inline void append_i32(std::vector<std::uint8_t>& output,
                       std::int32_t value) {
  std::uint32_t bits = 0;
  std::memcpy(&bits, &value, sizeof(bits));
  append_u32(output, bits);
}

inline std::uint32_t crc32(const std::uint8_t* data, std::size_t size) {
  std::uint32_t crc = 0xFFFFFFFFU;
  for (std::size_t index = 0; index < size; ++index) {
    crc ^= static_cast<std::uint32_t>(data[index]);
    for (int bit = 0; bit < 8; ++bit) {
      const std::uint32_t mask =
          static_cast<std::uint32_t>(-
              static_cast<std::int32_t>(crc & 1U));
      crc = (crc >> 1U) ^ (0xEDB88320U & mask);
    }
  }
  return crc ^ 0xFFFFFFFFU;
}

inline bool validate_header(const std::uint8_t* data, std::size_t size,
                            std::uint16_t expected_type,
                            std::size_t expected_size, std::string* error,
                            bool verify_crc) {
  if (data == nullptr || size != expected_size) {
    set_error(error, "packet length mismatch");
    return false;
  }
  if (read_u32(data) != kMagic) {
    set_error(error, "invalid magic");
    return false;
  }
  if (read_u16(data + 4) != kVersion) {
    set_error(error, "unsupported version");
    return false;
  }
  if (read_u16(data + 6) != expected_type) {
    set_error(error, "unexpected packet type");
    return false;
  }
  if (read_u16(data + 8) != expected_size) {
    set_error(error, "declared length mismatch");
    return false;
  }
  if (read_u16(data + 10) != 0) {
    set_error(error, "reserved field must be zero");
    return false;
  }
  if (verify_crc) {
    const auto expected = read_u32(data + expected_size - 4);
    const auto actual = crc32(data, expected_size - 4);
    if (expected != actual) {
      set_error(error, "CRC mismatch");
      return false;
    }
  }
  return true;
}

inline void append_header(std::vector<std::uint8_t>& output,
                          std::uint16_t packet_type,
                          std::uint16_t frame_size) {
  append_u32(output, kMagic);
  append_u16(output, kVersion);
  append_u16(output, packet_type);
  append_u16(output, frame_size);
  append_u16(output, 0);
}

}  // namespace detail

inline bool decode_control(const std::uint8_t* data, std::size_t size,
                           ControlFrame& frame, std::string* error = nullptr,
                           bool verify_crc = true) {
  if (!detail::validate_header(data, size, kControlPacketType,
                               kControlFrameSize, error, verify_crc)) {
    return false;
  }
  const auto raw_flags = detail::read_u32(data + 36);
  constexpr std::uint32_t known_flags =
      static_cast<std::uint32_t>(ControlFlags::kArmRequest) |
      static_cast<std::uint32_t>(ControlFlags::kDisarm) |
      static_cast<std::uint32_t>(ControlFlags::kEmergencyStop) |
      static_cast<std::uint32_t>(ControlFlags::kResetEstop) |
      static_cast<std::uint32_t>(ControlFlags::kStand) |
      static_cast<std::uint32_t>(ControlFlags::kLie);
  if ((raw_flags & ~known_flags) != 0U ||
      (raw_flags != 0U && (raw_flags & (raw_flags - 1U)) != 0U)) {
    detail::set_error(error, "invalid control flags");
    return false;
  }
  const float vx = detail::read_float(data + 40);
  const float vy = detail::read_float(data + 44);
  const float vyaw = detail::read_float(data + 48);
  if (!std::isfinite(vx) || !std::isfinite(vy) || !std::isfinite(vyaw)) {
    detail::set_error(error, "velocity must be finite");
    return false;
  }
  constexpr std::uint32_t command_flags =
      static_cast<std::uint32_t>(ControlFlags::kEmergencyStop) |
      static_cast<std::uint32_t>(ControlFlags::kResetEstop) |
      static_cast<std::uint32_t>(ControlFlags::kStand) |
      static_cast<std::uint32_t>(ControlFlags::kLie);
  if ((raw_flags & command_flags) != 0U &&
      (vx != 0.0F || vy != 0.0F || vyaw != 0.0F)) {
    detail::set_error(error, "discrete command requires zero velocity");
    return false;
  }
  frame = ControlFrame{
      detail::read_u64(data + 12),
      detail::read_u64(data + 20),
      detail::read_u64(data + 28),
      static_cast<ControlFlags>(raw_flags),
      vx,
      vy,
      vyaw,
  };
  return true;
}

inline bool decode_ack(const std::uint8_t* data, std::size_t size,
                       AckFrame& frame, std::string* error = nullptr,
                       bool verify_crc = true) {
  if (!detail::validate_header(data, size, kAckPacketType, kAckFrameSize,
                               error, verify_crc)) {
    return false;
  }
  const auto raw_state = detail::read_u32(data + 36);
  const auto raw_fault = detail::read_u32(data + 44);
  if (raw_state > static_cast<std::uint32_t>(GatewayState::kFault)) {
    detail::set_error(error, "unknown gateway state");
    return false;
  }
  const auto raw_flags = detail::read_u32(data + 48);
  constexpr std::uint32_t known_ack_flags =
      kAckEstopLatched | kAckCommandAccepted | kAckPostureStanding |
      kAckPostureLying;
  if (raw_fault > static_cast<std::uint32_t>(FaultReason::kEstop)) {
    detail::set_error(error, "unknown fault reason");
    return false;
  }
  if ((raw_flags & ~known_ack_flags) != 0U ||
      ((raw_flags & kAckPostureStanding) != 0U &&
       (raw_flags & kAckPostureLying) != 0U)) {
    detail::set_error(error, "invalid ACK flags");
    return false;
  }
  frame = AckFrame{
      detail::read_u64(data + 12),
      detail::read_u64(data + 20),
      detail::read_u64(data + 28),
      static_cast<GatewayState>(raw_state),
      detail::read_i32(data + 40),
      static_cast<FaultReason>(raw_fault),
      raw_flags,
  };
  return true;
}

inline std::vector<std::uint8_t> encode_control(const ControlFrame& frame) {
  const auto raw_flags = static_cast<std::uint32_t>(frame.flags);
  constexpr std::uint32_t known_flags =
      static_cast<std::uint32_t>(ControlFlags::kArmRequest) |
      static_cast<std::uint32_t>(ControlFlags::kDisarm) |
      static_cast<std::uint32_t>(ControlFlags::kEmergencyStop) |
      static_cast<std::uint32_t>(ControlFlags::kResetEstop) |
      static_cast<std::uint32_t>(ControlFlags::kStand) |
      static_cast<std::uint32_t>(ControlFlags::kLie);
  constexpr std::uint32_t command_flags =
      static_cast<std::uint32_t>(ControlFlags::kEmergencyStop) |
      static_cast<std::uint32_t>(ControlFlags::kResetEstop) |
      static_cast<std::uint32_t>(ControlFlags::kStand) |
      static_cast<std::uint32_t>(ControlFlags::kLie);
  if ((raw_flags & ~known_flags) != 0U ||
      (raw_flags != 0U && (raw_flags & (raw_flags - 1U)) != 0U) ||
      !std::isfinite(frame.vx) || !std::isfinite(frame.vy) ||
      !std::isfinite(frame.vyaw) ||
      ((raw_flags & command_flags) != 0U &&
       (frame.vx != 0.0F || frame.vy != 0.0F || frame.vyaw != 0.0F))) {
    throw std::invalid_argument("invalid control frame");
  }
  std::vector<std::uint8_t> output;
  output.reserve(kControlFrameSize);
  detail::append_header(output, kControlPacketType, kControlFrameSize);
  detail::append_u64(output, frame.session_id);
  detail::append_u64(output, frame.sequence);
  detail::append_u64(output, frame.arm_token);
  detail::append_u32(output, raw_flags);
  detail::append_float(output, frame.vx);
  detail::append_float(output, frame.vy);
  detail::append_float(output, frame.vyaw);
  detail::append_u32(output, detail::crc32(output.data(), output.size()));
  return output;
}

inline std::vector<std::uint8_t> encode_ack(const AckFrame& frame) {
  constexpr std::uint32_t known_ack_flags =
      kAckEstopLatched | kAckCommandAccepted | kAckPostureStanding |
      kAckPostureLying;
  if (static_cast<std::uint32_t>(frame.state) >
          static_cast<std::uint32_t>(GatewayState::kFault) ||
      static_cast<std::uint32_t>(frame.fault) >
          static_cast<std::uint32_t>(FaultReason::kEstop) ||
      (frame.flags & ~known_ack_flags) != 0U ||
      ((frame.flags & kAckPostureStanding) != 0U &&
       (frame.flags & kAckPostureLying) != 0U)) {
    throw std::invalid_argument("invalid ACK frame");
  }
  std::vector<std::uint8_t> output;
  output.reserve(kAckFrameSize);
  detail::append_header(output, kAckPacketType, kAckFrameSize);
  detail::append_u64(output, frame.session_id);
  detail::append_u64(output, frame.sequence);
  detail::append_u64(output, frame.arm_token);
  detail::append_u32(output, static_cast<std::uint32_t>(frame.state));
  detail::append_i32(output, frame.sdk_code);
  detail::append_u32(output, static_cast<std::uint32_t>(frame.fault));
  detail::append_u32(output, frame.flags);
  detail::append_u32(output, detail::crc32(output.data(), output.size()));
  return output;
}

}  // namespace go2_gateway
