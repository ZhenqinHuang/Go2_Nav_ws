# Go2 Move RPC Coalescing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop mapping every 20 Hz UDP heartbeat to a synchronous Unitree `Move()` RPC while preserving immediate ACK, watchdog StopMove, Disarm, and velocity updates.

**Architecture:** Keep the existing single-threaded UDP protocol and fail-closed state machine. `GatewayCore` records the velocity last applied to Unitree and the last SDK update time; identical heartbeats only refresh the watchdog and ACK, while changed velocity is coalesced to at most 10 Hz.

**Tech Stack:** C++17, Unitree SDK2 `SportClient`, CMake/CTest, existing fake `SportApi` unit tests.

---

### Task 1: Prove identical heartbeats currently spam Move

**Files:**
- Modify: `internal_gateway/test/gateway_core_test.cpp`

**Step 1: Write the failing test**

Extend `test_startup_and_arming()` after the first successful velocity frame:

```cpp
clock.now = 1.2;
const auto heartbeat = core.handle(frame(5, 201, 0, 0.2F));
require(heartbeat &&
            heartbeat->state == go2_gateway::GatewayState::kArmed,
        "identical heartbeat remains ARMED");
require(api.move_calls == 1,
        "identical heartbeat does not repeat Move RPC");
```

Renumber later sequence values in that test if necessary.

**Step 2: Run test to verify it fails**

Run on the inner Jetson build tree:

```bash
cmake -S internal_gateway -B /tmp/go2_gateway_red \
  -DGO2_GATEWAY_BUILD_SDK=OFF -DCMAKE_BUILD_TYPE=Debug
cmake --build /tmp/go2_gateway_red -j2
cd /tmp/go2_gateway_red && ctest --output-on-failure
```

Expected: `gateway_core_test` fails because `move_calls` is 2.

### Task 2: Prove rapid velocity changes must be coalesced

**Files:**
- Modify: `internal_gateway/test/gateway_core_test.cpp`

**Step 1: Write the failing test**

Add `test_move_updates_are_coalesced()`:

```cpp
void test_move_updates_are_coalesced() {
  FakeClock clock;
  FakeSportApi api;
  go2_gateway::GatewayConfig config;
  config.move_update_interval_sec = 0.1;
  go2_gateway::GatewayCore core(
      api, [&clock] { return clock(); }, config);

  require(core.handle(frame(
              1, 901, go2_gateway::ControlFlags::kArmRequest)),
          "Arm request accepted");
  clock.now = 1.0;
  require(core.handle(frame(2, 901)), "settling frame accepted");
  require(core.handle(frame(3, 901, 0, 0.2F)),
          "first Move accepted");
  require(api.move_calls == 1 && near(api.last_vx, 0.2F),
          "first Move applied immediately");

  clock.now = 1.05;
  require(core.handle(frame(4, 901, 0, 0.3F)),
          "rapid update ACKed");
  require(api.move_calls == 1,
          "rapid update does not call SDK yet");

  clock.now = 1.11;
  require(core.handle(frame(5, 901, 0, 0.4F)),
          "coalesced update ACKed");
  require(api.move_calls == 2 && near(api.last_vx, 0.4F),
          "latest velocity applied after interval");
}
```

Call the new test from `main()`.

**Step 2: Run test to verify it fails**

Run:

```bash
cmake --build /tmp/go2_gateway_red -j2
cd /tmp/go2_gateway_red && ctest --output-on-failure
```

Expected: compile failure because `GatewayConfig` has no
`move_update_interval_sec`, proving production support is absent.

### Task 3: Implement the minimal coalescing state

**Files:**
- Modify: `internal_gateway/include/go2_gateway/gateway_core.hpp`
- Modify: `internal_gateway/src/gateway_core.cpp`

**Step 1: Add configuration and state**

Add to `GatewayConfig`:

```cpp
double move_update_interval_sec{0.1};
float velocity_change_epsilon{1e-3F};
```

Add members:

```cpp
double last_move_at_{0.0};
float applied_vx_{0.0F};
float applied_vy_{0.0F};
float applied_vyaw_{0.0F};
```

Change:

```cpp
std::optional<AckFrame> process_velocity(
    const ControlFrame& frame, double now);
```

**Step 2: Implement Move suppression**

In `process_velocity()`:

```cpp
const bool velocity_changed =
    !moving_ ||
    std::fabs(vx - applied_vx_) > config_.velocity_change_epsilon ||
    std::fabs(vy - applied_vy_) > config_.velocity_change_epsilon ||
    std::fabs(vyaw - applied_vyaw_) > config_.velocity_change_epsilon;
const bool update_due =
    !moving_ ||
    now - last_move_at_ >= config_.move_update_interval_sec;

if (!velocity_changed || !update_due) {
  return make_ack(frame);
}
```

After a successful `Move()`:

```cpp
moving_ = true;
last_move_at_ = now;
applied_vx_ = vx;
applied_vy_ = vy;
applied_vyaw_ = vyaw;
```

Reset applied velocity whenever StopMove, Disarm, watchdog, SDK fault, or
shutdown clears `moving_`.

**Step 3: Run tests**

Run:

```bash
cmake --build /tmp/go2_gateway_red -j2
cd /tmp/go2_gateway_red && ctest --output-on-failure
```

Expected: 2/2 tests pass.

### Task 4: Run complete regressions and SDK build

**Files:**
- Test: `test/`
- Test: `internal_gateway/test/`

**Step 1: Run Python tests**

```bash
python3 -m pytest -q
```

Expected: all non-environment tests pass.

**Step 2: Build against the installed Unitree SDK**

On the inner Jetson:

```bash
build_dir="$(mktemp -d /tmp/go2-gateway-coalesce.XXXXXX)"
cmake -S internal_gateway -B "$build_dir" \
  -DGO2_GATEWAY_BUILD_SDK=ON -DCMAKE_BUILD_TYPE=Release
cmake --build "$build_dir" -j2
cd "$build_dir" && ctest --output-on-failure
```

Expected: SDK link succeeds and 2/2 CTests pass.

**Step 3: Commit**

```bash
git add internal_gateway/include/go2_gateway/gateway_core.hpp \
  internal_gateway/src/gateway_core.cpp \
  internal_gateway/test/gateway_core_test.cpp
git commit -m "fix: coalesce Unitree Move RPCs"
```

### Task 5: Deploy and perform staged physical verification

**Files:**
- Deploy: `/usr/local/bin/go2_cmd_gateway`

**Step 1: Back up and install**

Back up the current inner binary, stop the service, install the tested binary,
and restart the single systemd instance.

**Step 2: Restore external normal sender**

Use 20 Hz and default ACK/watchdog settings. Keep the Web console stopped until
physical verification finishes.

**Step 3: Verify short motion**

Auto-Arm once, send constant `vx=0.2`, stop after a short pulse, and verify:

- ACK remains online;
- repeated identical heartbeats cause one SDK Move call by unit tests;
- Stop/Disarm succeeds;
- native Go2 position changes.

**Step 4: Verify 1.5 m**

Run constant `vx=0.2` for 7.5 seconds, Stop/Disarm, and compare native
`sportmodestate.position` before and after.

**Step 5: Restore services**

Restore `localization_guard_enabled=true`, restart the Web console, keep direct
DDS disabled, and verify final status is online and Disarmed.
