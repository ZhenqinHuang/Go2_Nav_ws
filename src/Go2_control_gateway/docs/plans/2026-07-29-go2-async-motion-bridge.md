# Go2 Async Motion Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the next power-on session immediately testable by providing a non-blocking inner SDK motion pump, a corrected outer DDS bridge, and a guarded smoke-test command.

**Architecture:** The inner UDP process keeps protocol validation, watchdog, and ACK handling on its main thread while a `PumpedSportApi` worker owns repeated synchronous `SportClient.Move()` calls. The outer direct bridge remains a disabled diagnostic path, but adopts the known-working request header, `RecoveryStand`, and 10 Hz publish behavior from the reference repository.

**Tech Stack:** C++17, Unitree SDK2, ROS 2 Foxy `rclcpp`, `unitree_api`, Python 3/rclpy, CMake/CTest, pytest, systemd.

---

### Task 1: Restore the safe core baseline

**Files:**
- Modify: `internal_gateway/src/gateway_core.cpp`
- Modify: `internal_gateway/test/gateway_core_test.cpp`

**Step 1: Remove the failed synchronous 10 Hz experiment**

Restore the behavior where identical nonzero UDP heartbeats do not call
`SportApi::Move()` repeatedly. The worker introduced in Task 2 will own periodic
SDK refresh.

**Step 2: Run the existing core tests**

Run on a Linux build host:

```bash
cmake -S internal_gateway -B /tmp/go2-gateway-build -DGO2_GATEWAY_BUILD_SDK=OFF
cmake --build /tmp/go2-gateway-build -j2
cd /tmp/go2-gateway-build && ctest --output-on-failure
```

Expected: `2/2` tests pass.

**Step 3: Commit**

```bash
git add internal_gateway/src/gateway_core.cpp \
  internal_gateway/test/gateway_core_test.cpp
git commit -m "fix: restore nonblocking gateway core baseline"
```

### Task 2: Add the asynchronous SDK motion pump

**Files:**
- Create: `internal_gateway/include/go2_gateway/pumped_sport_api.hpp`
- Create: `internal_gateway/src/pumped_sport_api.cpp`
- Create: `internal_gateway/test/pumped_sport_api_test.cpp`
- Modify: `internal_gateway/include/go2_gateway/sport_api.hpp`
- Modify: `internal_gateway/CMakeLists.txt`

**Step 1: Write failing tests**

Add tests proving:

1. `Move()` returns immediately while the wrapped backend `Move()` is blocked;
2. the worker repeats the latest nonzero velocity;
3. a new velocity replaces the previous target without queueing history;
4. `StopMove()` prevents later Move calls and calls backend StopMove;
5. a backend Move error is returned once by `PollError()`.

Use a fake backend with mutexes and condition variables. Do not require Unitree
headers.

**Step 2: Run tests to verify RED**

Run the SDK-off CMake build.

Expected: compile failure because `make_pumped_sport_api` and `PollError` do not
exist.

**Step 3: Implement the minimal pump**

Add:

```cpp
virtual int PollError() { return 0; }

std::unique_ptr<SportApi> make_pumped_sport_api(
    std::unique_ptr<SportApi> backend,
    std::chrono::milliseconds move_period =
        std::chrono::milliseconds(100));
```

The pump owns:

- one worker thread;
- one latest-velocity slot;
- one backend-call mutex;
- one atomic/error slot;
- a condition variable for immediate first Move and shutdown.

No command queue is allowed.

**Step 4: Run tests to verify GREEN**

Expected: protocol, gateway core, and pump tests all pass.

**Step 5: Commit**

```bash
git add internal_gateway
git commit -m "feat: run Unitree Move calls on an SDK worker"
```

### Task 3: Propagate asynchronous SDK failures into fail-closed state

**Files:**
- Modify: `internal_gateway/src/gateway_core.cpp`
- Modify: `internal_gateway/test/gateway_core_test.cpp`
- Modify: `internal_gateway/src/unitree_sport_api.cpp`

**Step 1: Write a failing GatewayCore test**

Make the fake `SportApi::PollError()` return a nonzero SDK code after arming.
Call `core.tick()` and assert:

- returned ACK state is `LOCKED`;
- fault is `SDK`;
- SDK code is preserved;
- StopMove was requested.

**Step 2: Run test to verify RED**

Expected: GatewayCore remains ARMED because it does not poll the async error.

**Step 3: Implement fail-closed polling**

At the beginning of `GatewayCore::tick()`, consume `PollError()`. On nonzero,
call `force_locked(FaultReason::kSdk, code, true)` and return an ACK for the last
accepted session/sequence/token.

Wrap the synchronous Unitree backend:

```cpp
return make_pumped_sport_api(
    std::make_unique<SyncUnitreeSportApi>(interface_name),
    std::chrono::milliseconds(100));
```

**Step 4: Verify SDK-off tests**

Expected: all CTest cases pass.

**Step 5: Commit**

```bash
git add internal_gateway
git commit -m "fix: fail closed on asynchronous SDK errors"
```

### Task 4: Correct the outer DDS Sport request contract

**Worktree:** `D:/Github/Go2_Nav_ws/.worktrees/async-motion-bridge`

**Files:**
- Create: `src/Go2_nav2/include/common/sport_request.hpp`
- Create: `src/Go2_nav2/test/sport_request_test.cpp`
- Modify: `src/Go2_nav2/src/ros2_sport_client.cpp`
- Modify: `src/Go2_nav2/src/go2_cmd_vel_bridge.cpp`
- Modify: `src/Go2_nav2/config/cmd_vel_bridge_params.yaml`
- Modify: `src/Go2_nav2/CMakeLists.txt`

**Step 1: Write the failing Request contract test**

Assert that preparing two requests:

- gives nonzero, distinct `identity.id` values;
- sets the requested API ID;
- sets `lease.id=0`;
- sets `policy.priority=0`;
- sets `policy.noreply=true`.

**Step 2: Build on the outer Jetson to verify RED**

Transfer the package to a temporary directory and run:

```bash
source /opt/ros/foxy/setup.bash
source /home/nvidia/unitree_ros2/install/setup.bash
colcon build --base-paths src --packages-select go2_nav2
```

Expected: compile failure because `prepare_sport_request` is missing.

**Step 3: Implement request preparation**

Use a process-local atomic counter seeded from `steady_clock`. Call the helper
from `Move`, `StopMove`, and `RecoveryStand` before publishing.

**Step 4: Use RecoveryStand and 10 Hz**

Change both automatic motion preparation paths in
`go2_cmd_vel_bridge.cpp` from `StandUp` to `RecoveryStand`.
Change the compiled default and YAML `publish_rate_hz` to `10.0`.

**Step 5: Build and run test to verify GREEN**

Expected: package builds and `sport_request_test` passes on Foxy.

**Step 6: Commit**

```bash
git add src/Go2_nav2
git commit -m "fix: match working Go2 DDS motion request semantics"
```

### Task 5: Add a guarded power-on smoke-test command

**Files:**
- Create: `go2_control_gateway/smoke_test_core.py`
- Create: `go2_control_gateway/smoke_test_node.py`
- Create: `test/test_smoke_test_core.py`
- Modify: `setup.py`
- Modify: `docs/operations.md`

**Step 1: Write failing validation tests**

Test that the command refuses to run unless:

- `--confirm-safe` is supplied;
- `0 < vx <= 0.2`;
- `0 < duration <= 2.0`;
- preflight status is online, disarmed, and Nav2 inactive.

Also test that an ACK age over `0.4` requests immediate abort.

**Step 2: Run pytest to verify RED**

Expected: import failure because `smoke_test_core` is missing.

**Step 3: Implement the smoke test**

The ROS node must:

1. wait for gateway status;
2. verify the preflight contract;
3. call Arm;
4. wait for ARMED;
5. publish `/go2/manual_cmd_vel` at 20 Hz;
6. stop on duration, ACK fault, offline, Disarm, or Nav2 activation;
7. publish zero repeatedly in `finally`;
8. always request Disarm in `finally`;
9. print machine-readable PRECHECK/MOVE/STOP/FINAL lines.

**Step 4: Run pytest to verify GREEN**

Expected: all Python tests pass.

**Step 5: Commit**

```bash
git add go2_control_gateway test setup.py docs/operations.md
git commit -m "feat: add guarded Go2 motion smoke test"
```

### Task 6: Build, stage, and document the next power-on procedure

**Files:**
- Create: `docs/NEXT_POWER_ON_MOTION_TEST.md`
- Modify: `docs/operations.md`

**Step 1: Run complete offline verification**

```bash
python -m pytest -q
cmake -S internal_gateway -B /tmp/go2-gateway-build \
  -DGO2_GATEWAY_BUILD_SDK=OFF
cmake --build /tmp/go2-gateway-build -j2
cd /tmp/go2-gateway-build && ctest --output-on-failure
```

Build the outer `go2_nav2` package on the outer Jetson.

**Step 2: Deploy only power-safe components**

While the dog is powered off:

- deploy the outer Foxy package and smoke-test executable;
- keep `go2-direct-sport.service` disabled/inactive;
- keep the default sender localization guard enabled;
- do not enable or start any motion service.

The inner SDK binary cannot be linked or deployed until the inner board powers
on. Prepare the exact build/deploy command and backup path in the document.

**Step 3: Write the power-on checklist**

Document:

- network/interface/IP checks;
- battery threshold check;
- duplicate/legacy service check;
- direct DDS one-second A/B test;
- inner worker one-second test;
- required user safety confirmation;
- rollback commands;
- criteria for proceeding to 1 meter.

**Step 4: Verify final safe state**

Confirm on the outer Jetson:

- Web console HTTP 200;
- default sender is the only sender;
- localization guard is true;
- direct Sport service is disabled/inactive;
- no Arm request is active.

**Step 5: Commit**

```bash
git add docs
git commit -m "docs: add next power-on Go2 motion test checklist"
```
