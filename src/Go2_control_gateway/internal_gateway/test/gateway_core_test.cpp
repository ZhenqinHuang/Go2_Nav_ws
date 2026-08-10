#include "go2_gateway/gateway_core.hpp"

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(1);
  }
}

struct FakeClock {
  double now{0.0};
  double operator()() const { return now; }
};

class FakeSportApi final : public go2_gateway::SportApi {
 public:
  int BalanceStand() override {
    ++balance_calls;
    return balance_result;
  }

  int Move(float vx, float vy, float vyaw) override {
    ++move_calls;
    last_vx = vx;
    last_vy = vy;
    last_vyaw = vyaw;
    return move_result;
  }

  int StopMove() override {
    ++stop_calls;
    return stop_result;
  }

  int PollError() override {
    const int result = poll_error;
    poll_error = 0;
    return result;
  }

  int balance_calls{0};
  int move_calls{0};
  int stop_calls{0};
  int balance_result{0};
  int move_result{0};
  int stop_result{0};
  int poll_error{0};
  float last_vx{0.0F};
  float last_vy{0.0F};
  float last_vyaw{0.0F};
};

go2_gateway::ControlFrame frame(std::uint64_t sequence,
                                float vx = 0.0F, float vy = 0.0F,
                                float vyaw = 0.0F,
                                std::uint64_t session = 101,
                                std::uint64_t token = 0,
                                go2_gateway::ControlFlags flags =
                                    go2_gateway::ControlFlags::kNone) {
  return go2_gateway::ControlFrame{
      session, sequence, token, flags, vx, vy, vyaw};
}

void test_startup_and_direct_motion() {
  FakeClock clock;
  FakeSportApi api;
  go2_gateway::GatewayCore core(api, [&clock] { return clock(); });
  require(api.stop_calls == 1, "startup calls StopMove");
  require(core.state() == go2_gateway::GatewayState::kLocked,
          "wire-compatible state remains LOCKED");

  const auto moving = core.handle(frame(1, 0.2F));
  require(moving && moving->state == go2_gateway::GatewayState::kLocked,
          "token-zero velocity is ACKed without Arm");
  require(moving->arm_token == 0, "ACK keeps compatibility token zero");
  require(api.move_calls == 1, "first nonzero command calls Move directly");
  require(api.balance_calls == 0,
          "GatewayCore no longer performs Arm BalanceStand");

  clock.now = 0.05;
  const auto heartbeat = core.handle(frame(2, 0.2F));
  require(static_cast<bool>(heartbeat), "identical heartbeat is ACKed");
  require(api.move_calls == 1,
          "identical heartbeat does not repeat Move RPC");
}

void test_move_updates_are_coalesced() {
  FakeClock clock;
  FakeSportApi api;
  go2_gateway::GatewayConfig config;
  config.move_update_interval_sec = 0.1;
  go2_gateway::GatewayCore core(
      api, [&clock] { return clock(); }, config);

  require(static_cast<bool>(core.handle(frame(1, 0.2F))),
          "first Move accepted");
  require(api.move_calls == 1 &&
              std::fabs(api.last_vx - 0.2F) < 1e-6F,
          "first Move applied immediately");

  clock.now = 0.05;
  require(static_cast<bool>(core.handle(frame(2, 0.3F))),
          "rapid update ACKed");
  require(api.move_calls == 1, "rapid update does not call SDK yet");

  clock.now = 0.11;
  require(static_cast<bool>(core.handle(frame(3, 0.4F))),
          "coalesced update ACKed");
  require(api.move_calls == 2 &&
              std::fabs(api.last_vx - 0.4F) < 1e-6F,
          "latest velocity applied after interval");
}

void test_zero_stop_once_and_limits() {
  FakeClock clock;
  FakeSportApi api;
  go2_gateway::GatewayCore core(api, [&clock] { return clock(); });

  core.handle(frame(1, 2.0F, 1.0F, -3.0F));
  require(std::fabs(api.last_vx - 0.6F) < 1e-6F, "vx hard limit");
  require(api.last_vy == 0.0F, "vy forced to zero");
  require(std::fabs(api.last_vyaw + 1.4F) < 1e-6F, "vyaw hard limit");

  const int stops_before = api.stop_calls;
  clock.now = 0.01;
  core.handle(frame(2));
  require(api.stop_calls == stops_before + 1, "first zero calls StopMove");
  clock.now = 0.02;
  core.handle(frame(3));
  require(api.stop_calls == stops_before + 1,
          "repeated zero does not spam StopMove");
}

void test_arm_fields_are_rejected() {
  FakeClock clock;
  FakeSportApi api;
  go2_gateway::GatewayCore core(api, [&clock] { return clock(); });

  require(!core.handle(frame(1, 0.2F, 0.0F, 0.0F, 101, 99)),
          "nonzero Arm token is rejected");
  require(!core.handle(frame(
              2, 0.2F, 0.0F, 0.0F, 101, 99,
              go2_gateway::ControlFlags::kArmRequest)),
          "Arm request flag is rejected");
  require(!core.handle(frame(
              3, 0.0F, 0.0F, 0.0F, 101, 0,
              go2_gateway::ControlFlags::kDisarm)),
          "Disarm flag is rejected");
  require(api.move_calls == 0, "rejected Arm frames never call Move");
  require(api.balance_calls == 0,
          "rejected Arm frames never call BalanceStand");
}

void test_replay_and_watchdog_stop_motion() {
  FakeClock clock;
  FakeSportApi api;
  go2_gateway::GatewayCore core(api, [&clock] { return clock(); });

  require(static_cast<bool>(core.handle(frame(1, 0.2F))),
          "motion starts");
  clock.now = 0.2;
  require(!core.handle(frame(1, 0.3F)), "replayed frame rejected");
  clock.now = 0.51;
  const auto timeout = core.tick();
  require(timeout && timeout->fault == go2_gateway::FaultReason::kWatchdog,
          "replay does not refresh watchdog");
  require(timeout->state == go2_gateway::GatewayState::kLocked,
          "watchdog ACK uses compatibility LOCKED state");
  require(api.stop_calls == 2,
          "watchdog calls StopMove after startup stop");

  clock.now = 1.2;
  require(!core.tick(), "stopped gateway does not repeat watchdog stop");
}

void test_session_change_stops_before_accepting_new_session() {
  FakeClock clock;
  FakeSportApi api;
  go2_gateway::GatewayCore core(api, [&clock] { return clock(); });
  require(static_cast<bool>(core.handle(frame(1, 0.2F))),
          "first session starts motion");

  clock.now = 0.1;
  const auto changed = core.handle(frame(1, 0.3F, 0.0F, 0.0F, 202));
  require(changed &&
              changed->fault == go2_gateway::FaultReason::kProtocol,
          "new session is ACKed with protocol reset");
  require(api.stop_calls == 2, "session change stops old motion");
  require(api.move_calls == 1,
          "first frame of new session is not applied as motion");

  clock.now = 0.2;
  const auto resumed = core.handle(frame(2, 0.3F, 0.0F, 0.0F, 202));
  require(resumed && resumed->fault == go2_gateway::FaultReason::kNone,
          "next frame in new session resumes normal operation");
  require(api.move_calls == 2, "new session can drive after reset frame");
}

void test_sdk_failures_stop_motion() {
  {
    FakeClock clock;
    FakeSportApi api;
    api.move_result = -9;
    go2_gateway::GatewayCore core(api, [&clock] { return clock(); });
    const auto failed = core.handle(frame(1, 0.2F));
    require(failed && failed->fault == go2_gateway::FaultReason::kSdk,
            "synchronous SDK failure is reported");
    require(failed->sdk_code == -9, "SDK code is preserved");
    require(api.stop_calls == 2, "SDK failure requests StopMove");
  }

  {
    FakeClock clock;
    FakeSportApi api;
    go2_gateway::GatewayCore core(api, [&clock] { return clock(); });
    require(static_cast<bool>(core.handle(frame(1, 0.2F))),
            "motion starts");
    const int stops_before = api.stop_calls;
    api.poll_error = -17;
    clock.now = 0.1;
    const auto failed = core.tick();
    require(failed && failed->fault == go2_gateway::FaultReason::kSdk,
            "async SDK failure produces an ACK");
    require(failed->sdk_code == -17, "async SDK code is preserved");
    require(api.stop_calls == stops_before + 1,
            "async SDK failure requests StopMove");
  }
}

}  // namespace

int main() {
  test_startup_and_direct_motion();
  test_move_updates_are_coalesced();
  test_zero_stop_once_and_limits();
  test_arm_fields_are_rejected();
  test_replay_and_watchdog_stop_motion();
  test_session_change_stops_before_accepting_new_session();
  test_sdk_failures_stop_motion();
  std::cout << "gateway_core_test: PASS\n";
  return 0;
}
