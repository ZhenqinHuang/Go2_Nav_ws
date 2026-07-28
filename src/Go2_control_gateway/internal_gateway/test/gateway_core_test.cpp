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

  int balance_calls{0};
  int move_calls{0};
  int stop_calls{0};
  int balance_result{0};
  int move_result{0};
  int stop_result{0};
  float last_vx{0.0F};
  float last_vy{0.0F};
  float last_vyaw{0.0F};
};

go2_gateway::ControlFrame frame(std::uint64_t sequence,
                                std::uint64_t token,
                                go2_gateway::ControlFlags flags,
                                float vx = 0.0F, float vy = 0.0F,
                                float vyaw = 0.0F,
                                std::uint64_t session = 101) {
  return go2_gateway::ControlFrame{
      session, sequence, token, flags, vx, vy, vyaw};
}

void arm_and_settle(go2_gateway::GatewayCore& core, FakeClock& clock,
                    std::uint64_t token = 201) {
  const auto arming =
      core.handle(frame(1, token, go2_gateway::ControlFlags::kArmRequest));
  require(arming && arming->state == go2_gateway::GatewayState::kArming,
          "Arm enters ARMING");
  clock.now = 0.4;
  core.handle(frame(2, token, go2_gateway::ControlFlags::kNone));
  clock.now = 0.79;
  core.handle(frame(3, token, go2_gateway::ControlFlags::kNone));
  clock.now = 0.81;
  const auto armed =
      core.handle(frame(4, token, go2_gateway::ControlFlags::kNone));
  require(armed && armed->state == go2_gateway::GatewayState::kArmed,
          "settle interval enters ARMED");
}

void test_startup_and_arming() {
  FakeClock clock;
  FakeSportApi api;
  go2_gateway::GatewayCore core(api, [&clock] { return clock(); });
  require(api.stop_calls == 1, "startup calls StopMove");
  require(core.state() == go2_gateway::GatewayState::kLocked,
          "startup is LOCKED");

  const auto arming =
      core.handle(frame(1, 201, go2_gateway::ControlFlags::kArmRequest));
  require(arming && arming->state == go2_gateway::GatewayState::kArming,
          "fresh token starts arming");
  require(api.balance_calls == 1, "BalanceStand called once");

  clock.now = 0.4;
  const auto blocked =
      core.handle(frame(2, 201, go2_gateway::ControlFlags::kNone, 0.2F));
  require(blocked && blocked->state == go2_gateway::GatewayState::kArming,
          "movement blocked while settling");
  require(api.move_calls == 0, "Move blocked while arming");

  clock.now = 0.79;
  core.handle(frame(3, 201, go2_gateway::ControlFlags::kNone));
  clock.now = 0.81;
  const auto moving =
      core.handle(frame(4, 201, go2_gateway::ControlFlags::kNone, 0.2F));
  require(moving && moving->state == go2_gateway::GatewayState::kArmed,
          "settled state is ARMED");
  require(api.move_calls == 1, "ARMED nonzero command calls Move");
  require(api.balance_calls == 1, "BalanceStand is not repeated");
}

void test_zero_stop_once_and_limits() {
  FakeClock clock;
  FakeSportApi api;
  go2_gateway::GatewayCore core(api, [&clock] { return clock(); });
  arm_and_settle(core, clock);

  clock.now = 0.82;
  core.handle(frame(5, 201, go2_gateway::ControlFlags::kNone, 2.0F, 1.0F,
                    -3.0F));
  require(std::fabs(api.last_vx - 0.6F) < 1e-6F, "vx hard limit");
  require(api.last_vy == 0.0F, "vy forced to zero");
  require(std::fabs(api.last_vyaw + 1.4F) < 1e-6F, "vyaw hard limit");

  const int stops_before = api.stop_calls;
  clock.now = 0.83;
  core.handle(frame(6, 201, go2_gateway::ControlFlags::kNone));
  require(api.stop_calls == stops_before + 1, "first zero calls StopMove");
  clock.now = 0.84;
  core.handle(frame(7, 201, go2_gateway::ControlFlags::kNone));
  require(api.stop_calls == stops_before + 1, "repeated zero does not spam stop");
  require(core.state() == go2_gateway::GatewayState::kArmed,
          "zero retains Arm");
}

void test_replay_watchdog_and_revocation() {
  FakeClock clock;
  FakeSportApi api;
  go2_gateway::GatewayCore core(api, [&clock] { return clock(); });
  arm_and_settle(core, clock);

  clock.now = 1.0;
  require(!core.handle(frame(4, 201, go2_gateway::ControlFlags::kNone)),
          "replayed frame rejected");
  clock.now = 1.32;
  const auto timeout = core.tick();
  require(timeout && timeout->fault == go2_gateway::FaultReason::kWatchdog,
          "replay does not refresh watchdog");
  require(core.state() == go2_gateway::GatewayState::kLocked,
          "watchdog locks gateway");
  require(core.is_token_revoked(201), "watchdog revokes token");

  clock.now = 1.33;
  require(!core.handle(
              frame(5, 201, go2_gateway::ControlFlags::kArmRequest)),
          "revoked token cannot re-arm");
  require(api.balance_calls == 1, "revoked token never calls BalanceStand");
}

void test_disarm_and_sdk_failure_lock() {
  {
    FakeClock clock;
    FakeSportApi api;
    go2_gateway::GatewayCore core(api, [&clock] { return clock(); });
    arm_and_settle(core, clock);
    const auto disarmed =
        core.handle(frame(5, 201, go2_gateway::ControlFlags::kDisarm));
    require(disarmed &&
                disarmed->fault ==
                    go2_gateway::FaultReason::kExplicitDisarm,
            "Disarm reports explicit reason");
    require(core.state() == go2_gateway::GatewayState::kLocked,
            "Disarm locks");
  }

  {
    FakeClock clock;
    FakeSportApi api;
    go2_gateway::GatewayCore core(api, [&clock] { return clock(); });
    arm_and_settle(core, clock);
    api.move_result = -9;
    clock.now = 0.82;
    const auto failed =
        core.handle(frame(5, 201, go2_gateway::ControlFlags::kNone, 0.2F));
    require(failed && failed->fault == go2_gateway::FaultReason::kSdk,
            "SDK failure is reported");
    require(failed->sdk_code == -9, "SDK code is preserved");
    require(core.state() == go2_gateway::GatewayState::kLocked,
            "SDK failure locks");
  }
}

}  // namespace

int main() {
  test_startup_and_arming();
  test_zero_stop_once_and_limits();
  test_replay_watchdog_and_revocation();
  test_disarm_and_sdk_failure_lock();
  std::cout << "gateway_core_test: PASS\n";
  return 0;
}
