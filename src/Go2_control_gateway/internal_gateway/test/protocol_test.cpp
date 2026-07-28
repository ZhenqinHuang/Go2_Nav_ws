#include "go2_gateway/protocol.hpp"

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(1);
  }
}

std::vector<std::uint8_t> from_hex(const std::string& text) {
  require(text.size() % 2 == 0, "hex string length");
  std::vector<std::uint8_t> result;
  result.reserve(text.size() / 2);
  for (std::size_t index = 0; index < text.size(); index += 2) {
    result.push_back(static_cast<std::uint8_t>(
        std::stoul(text.substr(index, 2), nullptr, 16)));
  }
  return result;
}

}  // namespace

int main() {
  using namespace go2_gateway;
  const auto control_golden = from_hex(
      "4732475700010001003800000102030405060708"
      "0000000000000009000000000000000a00000001"
      "3e4ccccd00000000be99999a473d1b0a");
  const auto ack_golden = from_hex(
      "4732475700010002003800000102030405060708"
      "0000000000000009000000000000000a00000002"
      "000000000000000000000000704b9c8c");

  require(kControlFrameSize == 56, "control size is fixed");
  require(kAckFrameSize == 56, "ACK size is fixed");

  ControlFrame control{};
  std::string error;
  require(decode_control(control_golden.data(), control_golden.size(), control,
                         &error),
          error.c_str());
  require(control.session_id == 0x0102030405060708ULL, "control session");
  require(control.sequence == 9, "control sequence");
  require(control.arm_token == 10, "control token");
  require(control.flags == ControlFlags::kArmRequest, "control flags");
  require(std::fabs(control.vx - 0.2F) < 1e-6F, "control vx");
  require(std::fabs(control.vyaw + 0.3F) < 1e-6F, "control vyaw");
  require(encode_control(control) == control_golden, "control golden encode");

  AckFrame ack{};
  require(decode_ack(ack_golden.data(), ack_golden.size(), ack, &error),
          error.c_str());
  require(ack.state == GatewayState::kArmed, "ACK state");
  require(encode_ack(ack) == ack_golden, "ACK golden encode");

  auto corrupted = control_golden;
  corrupted[20] ^= 0x01;
  require(!decode_control(corrupted.data(), corrupted.size(), control, &error),
          "corrupted CRC must fail");

  auto invalid_float = control_golden;
  invalid_float[44] = 0x7f;
  invalid_float[45] = 0xc0;
  invalid_float[46] = 0x00;
  invalid_float[47] = 0x00;
  require(!decode_control(invalid_float.data(), invalid_float.size(), control,
                          &error, false),
          "NaN velocity must fail");

  std::cout << "protocol_test: PASS\n";
  return 0;
}
