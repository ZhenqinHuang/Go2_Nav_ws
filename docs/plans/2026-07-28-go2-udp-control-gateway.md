# Go2 UDP Control Gateway Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Route Nav2 and authenticated manual velocity commands from the external Jetson to a fail-closed Unitree SDK gateway on the internal computer, with a LAN control console and documented deployment.

**Architecture:** A ROS 2 Python node on the external Jetson validates and arbitrates `/cmd_vel` sources, then sends versioned CRC-protected UDP control frames over `eth0`. A standalone C++ daemon on the internal computer validates the frames, owns the Arm state machine, and invokes the native Unitree `SportClient`; an authenticated `aiohttp` console uses ROS 2 services/topics without exposing write-capable rosbridge access to the LAN.

**Tech Stack:** ROS 2 Foxy (`rclpy`), Python 3.8, `aiohttp`, HTML/CSS/JavaScript, UDP, C++17, Unitree SDK2, CMake/CTest, systemd, pytest.

---

## Global constraints

- Work only in branch `codex/go2-udp-gateway`.
- Preserve the existing direct DDS bridge and all radar/localization behavior.
- Do not perform physical motion until the no-motion deployment checks pass and the user confirms the area is safe.
- Use monotonic time for all watchdogs; do not depend on the unsynchronized internal system clock.
- Treat invalid packets, SDK errors, control-link timeout, console lease loss, and process restarts as fail-closed conditions.
- Do not store web console passwords in plaintext.
- Do not expose authenticated control endpoints to the public Internet.

### Task 1: Scaffold the control gateway package

**Files:**

- Create: `src/Go2_control_gateway/package.xml`
- Create: `src/Go2_control_gateway/setup.py`
- Create: `src/Go2_control_gateway/setup.cfg`
- Create: `src/Go2_control_gateway/resource/Go2_control_gateway`
- Create: `src/Go2_control_gateway/go2_control_gateway/__init__.py`
- Create: `src/Go2_control_gateway/test/test_package_layout.py`

**Step 1: Write the failing test**

Create a package-layout test that imports `go2_control_gateway` and asserts that
the declared console static directory and configuration directory exist.

```python
def test_package_exposes_runtime_directories():
    package_root = Path(gateway.__file__).parent
    assert (package_root / "web").is_dir()
    assert (package_root / "config").is_dir()
```

**Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest src/Go2_control_gateway/test/test_package_layout.py -q
```

Expected: FAIL because the package/runtime directories do not exist.

**Step 3: Add the minimal ROS 2 Python package**

Declare runtime dependencies for `rclpy`, `geometry_msgs`, `nav_msgs`,
`std_msgs`, `std_srvs`, `action_msgs`, `nav2_msgs`, and `unitree_go`. Install
config, launch, web, and systemd assets through `data_files`.

**Step 4: Run the test to verify it passes**

Run the command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add src/Go2_control_gateway
git commit -m "build: scaffold Go2 control gateway package"
```

### Task 2: Implement the cross-language UDP protocol

**Files:**

- Create: `src/Go2_control_gateway/go2_control_gateway/protocol.py`
- Create: `src/Go2_control_gateway/internal_gateway/include/go2_gateway/protocol.hpp`
- Create: `src/Go2_control_gateway/test/test_protocol.py`
- Create: `src/Go2_control_gateway/internal_gateway/test/protocol_test.cpp`
- Create: `src/Go2_control_gateway/internal_gateway/test/golden_vectors.txt`

**Step 1: Write failing Python protocol tests**

Cover:

- exact 56-byte control and ACK frame sizes;
- network byte order;
- Python encode/decode round trip;
- golden byte vectors;
- CRC corruption rejection;
- wrong magic/version/type/length rejection;
- NaN/Inf rejection;
- flag and enum validation.

Representative test:

```python
def test_control_crc_corruption_is_rejected():
    frame = bytearray(encode_control(valid_control()))
    frame[20] ^= 0x01
    with pytest.raises(ProtocolError, match="crc"):
        decode_control(bytes(frame))
```

**Step 2: Verify RED**

Run:

```powershell
python -m pytest src/Go2_control_gateway/test/test_protocol.py -q
```

Expected: FAIL because `protocol.py` is missing.

**Step 3: Implement the minimal Python protocol**

Use `struct.Struct("!IHHHHQQQIfffI")` for control frames and an equally sized
ACK structure. Compute `zlib.crc32()` over all bytes except the trailing CRC.
Expose typed immutable dataclasses and explicit `ProtocolError` exceptions.

**Step 4: Verify Python GREEN**

Run the command from Step 2.

Expected: all protocol tests PASS.

**Step 5: Write the failing C++ golden-vector test**

The C++ test must decode the Python-generated golden frame, encode it back to
identical bytes, and reject a corrupted CRC.

**Step 6: Verify C++ RED**

When an aarch64 Ubuntu build environment is available, run:

```bash
cmake -S src/Go2_control_gateway/internal_gateway \
      -B /tmp/go2_gateway_protocol_build \
      -DGO2_GATEWAY_PROTOCOL_ONLY=ON
cmake --build /tmp/go2_gateway_protocol_build -j2
ctest --test-dir /tmp/go2_gateway_protocol_build --output-on-failure
```

Expected: FAIL because the C++ protocol implementation is incomplete.

**Step 7: Implement the minimal header-only C++ codec**

Implement explicit big-endian integer/IEEE-754 float conversion and an internal
CRC32 function. Do not cast packed network buffers directly to structs.

**Step 8: Verify C++ GREEN**

Repeat Step 6.

Expected: all C++ protocol tests PASS.

**Step 9: Commit**

```bash
git add src/Go2_control_gateway
git commit -m "feat: add versioned UDP gateway protocol"
```

### Task 3: Implement the external sender core

**Files:**

- Create: `src/Go2_control_gateway/go2_control_gateway/sender_core.py`
- Create: `src/Go2_control_gateway/test/test_sender_core.py`

**Step 1: Write failing sender-core tests**

Cover:

- process starts LOCKED with zero velocity;
- Arm creates a new token and never reuses a revoked token;
- only a matching ARMED ACK confirms Arm;
- ACK timeout clears Arm and forces zero;
- Nav2 velocity timeout sends zero but remains armed;
- manual command is rejected while Nav2 is active;
- manual command is accepted only while Nav2 is idle and the manual heartbeat is fresh;
- limits, deadband, yaw EMA, NaN/Inf handling;
- localization stale/correction guard forces zero;
- sequence increases monotonically within a session.

Representative test:

```python
def test_link_timeout_revokes_arm_and_cannot_auto_rearm(clock):
    core = armed_core(clock)
    old_token = core.arm_token
    clock.advance(0.51)
    packet = core.next_packet()
    assert not core.is_armed
    assert packet.vx == 0.0
    assert packet.arm_token != old_token or not packet.arm_requested
```

**Step 2: Verify RED**

```powershell
python -m pytest src/Go2_control_gateway/test/test_sender_core.py -q
```

Expected: FAIL because `sender_core.py` is missing.

**Step 3: Implement minimal pure-Python state logic**

Inject a monotonic clock and random-token supplier. Keep ROS 2 and sockets out
of this module so the safety behavior is deterministic and testable.

**Step 4: Verify GREEN**

Repeat Step 2.

Expected: all sender-core tests PASS.

**Step 5: Commit**

```bash
git add src/Go2_control_gateway/go2_control_gateway/sender_core.py \
        src/Go2_control_gateway/test/test_sender_core.py
git commit -m "feat: add fail-closed sender state machine"
```

### Task 4: Add the external ROS 2 UDP sender node

**Files:**

- Create: `src/Go2_control_gateway/go2_control_gateway/udp_sender_node.py`
- Create: `src/Go2_control_gateway/launch/udp_sender.launch.py`
- Create: `src/Go2_control_gateway/config/udp_sender.yaml`
- Create: `src/Go2_control_gateway/test/test_udp_sender_adapter.py`
- Modify: `src/Go2_control_gateway/setup.py`

**Step 1: Write failing adapter tests**

Use small fake publisher/socket adapters to verify:

- UDP socket binds `192.168.123.5:15001`;
- destination is `192.168.123.18:15000`;
- the timer sends at configured 20 Hz;
- ACK receiver updates the core;
- Arm service waits at most 1.0 s for a matching ACK;
- status is published as JSON without credentials or secrets;
- shutdown sends repeated Disarm/zero frames.

**Step 2: Verify RED**

```powershell
python -m pytest src/Go2_control_gateway/test/test_udp_sender_adapter.py -q
```

Expected: FAIL because the node adapter is missing.

**Step 3: Implement the ROS 2 adapter**

Subscribe to:

- `/cmd_vel`;
- `/go2/manual_cmd_vel`;
- `/map_to_odom`;
- `/navigate_to_pose/_action/status`.

Provide:

- `/go2_cmd_vel_gateway/arm` (`std_srvs/SetBool`);
- `/go2_cmd_vel_gateway/status` (`std_msgs/String`).

Use a receiver thread for ACKs and a `MultiThreadedExecutor` so service calls do
not block ACK handling.

**Step 4: Verify GREEN and syntax**

```powershell
python -m pytest src/Go2_control_gateway/test/test_udp_sender_adapter.py -q
python -m compileall -q src/Go2_control_gateway/go2_control_gateway
```

Expected: PASS, exit code 0.

**Step 5: Commit**

```bash
git add src/Go2_control_gateway
git commit -m "feat: add ROS 2 UDP velocity sender"
```

### Task 5: Implement and test the internal fail-closed core

**Files:**

- Create: `src/Go2_control_gateway/internal_gateway/include/go2_gateway/gateway_core.hpp`
- Create: `src/Go2_control_gateway/internal_gateway/src/gateway_core.cpp`
- Create: `src/Go2_control_gateway/internal_gateway/test/gateway_core_test.cpp`
- Create: `src/Go2_control_gateway/internal_gateway/CMakeLists.txt`

**Step 1: Write the failing C++ state-machine test**

Inject a fake `SportApi` interface and monotonic clock. Cover:

- startup calls StopMove and remains LOCKED;
- a fresh Arm token calls BalanceStand once;
- movement is blocked during the 0.8 s ARMING interval;
- ARMED nonzero frames call Move;
- zero frames call StopMove once and retain Arm;
- invalid/replayed frames do not refresh watchdog;
- 0.5 s timeout calls StopMove and revokes the token;
- the revoked token cannot re-arm;
- Disarm and SDK nonzero errors force LOCKED;
- speed limits are enforced internally.

**Step 2: Verify RED**

```bash
cmake -S src/Go2_control_gateway/internal_gateway \
      -B /tmp/go2_gateway_core_build \
      -DGO2_GATEWAY_BUILD_SDK=OFF
cmake --build /tmp/go2_gateway_core_build -j2
ctest --test-dir /tmp/go2_gateway_core_build --output-on-failure
```

Expected: FAIL because the state machine is missing.

**Step 3: Implement the minimal state machine**

`GatewayCore` returns required effects (`BalanceStand`, `Move`, `StopMove`) and
ACK state. UDP and SDK code must not be embedded in transition logic.

**Step 4: Verify GREEN**

Repeat Step 2.

Expected: all core tests PASS.

**Step 5: Commit**

```bash
git add src/Go2_control_gateway/internal_gateway
git commit -m "feat: add internal gateway safety core"
```

### Task 6: Add the internal UDP daemon and Unitree SDK adapter

**Files:**

- Create: `src/Go2_control_gateway/internal_gateway/src/main.cpp`
- Create: `src/Go2_control_gateway/internal_gateway/include/go2_gateway/sport_api.hpp`
- Create: `src/Go2_control_gateway/internal_gateway/src/unitree_sport_api.cpp`
- Create: `src/Go2_control_gateway/internal_gateway/src/dry_run_sport_api.cpp`
- Create: `src/Go2_control_gateway/internal_gateway/test/udp_integration_test.py`
- Modify: `src/Go2_control_gateway/internal_gateway/CMakeLists.txt`

**Step 1: Write the failing dry-run integration test**

Launch the daemon with `--dry-run`, send valid/invalid UDP frames, and assert:

- ACK source/destination and sequence correlation;
- Arm transitions LOCKED → ARMING → ARMED;
- invalid CRC receives no state-changing ACK;
- link timeout returns LOCKED and reports watchdog reason;
- old token cannot re-arm.

**Step 2: Verify RED**

```bash
python3 src/Go2_control_gateway/internal_gateway/test/udp_integration_test.py \
  --gateway /tmp/go2_gateway_core_build/go2_cmd_gateway
```

Expected: FAIL because the daemon/adapter is missing.

**Step 3: Implement the UDP daemon and adapters**

The production adapter initializes:

```cpp
ChannelFactory::Instance()->Init(0, "eth0");
SportClient client;
client.SetTimeout(3.0f);
client.Init();
```

Bind only the configured address/port. Install signal handlers that set a stop
flag; the normal exit path calls `StopMove()`.

**Step 4: Verify dry-run GREEN**

Build and repeat Step 2.

Expected: all integration scenarios PASS without robot motion.

**Step 5: Verify Unitree link build on the internal computer**

```bash
cmake -S src/Go2_control_gateway/internal_gateway \
      -B /tmp/go2_gateway_sdk_build \
      -DGO2_GATEWAY_BUILD_SDK=ON
cmake --build /tmp/go2_gateway_sdk_build -j2
ldd /tmp/go2_gateway_sdk_build/go2_cmd_gateway
```

Expected: build exit 0; no `not found` libraries.

**Step 6: Commit**

```bash
git add src/Go2_control_gateway/internal_gateway
git commit -m "feat: add Unitree SDK UDP gateway daemon"
```

### Task 7: Implement console authentication and control policy

**Files:**

- Create: `src/Go2_control_gateway/go2_control_gateway/console_core.py`
- Create: `src/Go2_control_gateway/test/test_console_core.py`

**Step 1: Write failing console-core tests**

Cover:

- scrypt password verification;
- generic authentication errors;
- random opaque session identifiers;
- idle and absolute session expiration;
- one active control lease;
- lease release on logout/WebSocket disconnect;
- Nav2-active rejection of manual control;
- manual heartbeat expiry returns zero;
- Disarm is permitted even without a control lease after authentication;
- no password hash/token appears in public state.

**Step 2: Verify RED**

```powershell
python -m pytest src/Go2_control_gateway/test/test_console_core.py -q
```

Expected: FAIL because `console_core.py` is missing.

**Step 3: Implement the minimal policy classes**

Use `hashlib.scrypt`, `hmac.compare_digest`, and `secrets.token_urlsafe`.
Keep sessions server-side and send only an HttpOnly `SameSite=Strict` cookie.

**Step 4: Verify GREEN**

Repeat Step 2.

Expected: all console policy tests PASS.

**Step 5: Commit**

```bash
git add src/Go2_control_gateway/go2_control_gateway/console_core.py \
        src/Go2_control_gateway/test/test_console_core.py
git commit -m "feat: add console authentication and control lease"
```

### Task 8: Implement the authenticated console backend

**Files:**

- Create: `src/Go2_control_gateway/go2_control_gateway/console_server.py`
- Create: `src/Go2_control_gateway/go2_control_gateway/ros_adapter.py`
- Create: `src/Go2_control_gateway/go2_control_gateway/set_console_password.py`
- Create: `src/Go2_control_gateway/config/console.yaml`
- Create: `src/Go2_control_gateway/test/test_console_http.py`
- Modify: `src/Go2_control_gateway/setup.py`

**Step 1: Write failing HTTP/API tests**

Using `aiohttp.test_utils`, cover:

- unauthenticated API and WebSocket rejection;
- login success/failure and secure cookie attributes appropriate for trusted-LAN HTTP;
- CSRF token requirement for state-changing requests;
- control lease acquisition/conflict/release;
- Arm/Disarm forwarding;
- manual command rejection while Nav2 is active;
- cancel-navigation forwarding;
- browser heartbeat loss sends zero;
- API rate and body-size limits.

**Step 2: Verify RED**

```powershell
python -m pytest src/Go2_control_gateway/test/test_console_http.py -q
```

Expected: FAIL because the server is missing.

**Step 3: Implement the backend**

Serve:

- `POST /api/login`, `POST /api/logout`;
- `GET /api/state`;
- `POST /api/control/acquire`, `/api/control/release`;
- `POST /api/arm`, `/api/disarm`;
- `POST /api/manual`;
- `POST /api/navigation/cancel`;
- `/ws/state`;
- static files under `/`.

Bind `192.168.0.101:8080` by default. Use ROS 2 only through `RosAdapter`;
never accept arbitrary topic/service names from the browser.

**Step 4: Verify GREEN**

```powershell
python -m pytest src/Go2_control_gateway/test/test_console_http.py -q
python -m compileall -q src/Go2_control_gateway/go2_control_gateway
```

Expected: PASS.

**Step 5: Commit**

```bash
git add src/Go2_control_gateway
git commit -m "feat: add authenticated LAN console backend"
```

### Task 9: Build the LAN console frontend

**Files:**

- Create: `src/Go2_control_gateway/go2_control_gateway/web/index.html`
- Create: `src/Go2_control_gateway/go2_control_gateway/web/app.css`
- Create: `src/Go2_control_gateway/go2_control_gateway/web/app.js`
- Create: `src/Go2_control_gateway/test/test_web_contract.py`

**Step 1: Write the failing web contract test**

Assert that the page includes:

- login form;
- connection/Arm/Nav2 indicators;
- battery, mode, velocity and odometry values;
- Arm confirmation and always-visible Disarm;
- cancel navigation;
- hold-to-run movement controls;
- manual linear/angular speed controls;
- accessibility labels and keyboard-release/blur handlers;
- no direct rosbridge or arbitrary ROS topic calls.

**Step 2: Verify RED**

```powershell
python -m pytest src/Go2_control_gateway/test/test_web_contract.py -q
```

Expected: FAIL because the web assets are missing.

**Step 3: Implement the responsive frontend**

Use plain HTML/CSS/JavaScript so no Node/Vite runtime is required on the robot.
Movement commands are generated only while pointer/keyboard input remains held.
`pointerup`, `pointercancel`, `keyup`, `blur`, visibility loss, lease loss and
WebSocket loss all send zero.

**Step 4: Verify GREEN**

Repeat Step 2.

Expected: PASS.

**Step 5: Run a local demo and browser smoke test**

Start the backend in demo mode and verify desktop/mobile layouts, authentication,
Arm confirmation, disabled controls during Nav2, and release-to-stop behavior.
Capture a screenshot for the deployment record.

**Step 6: Commit**

```bash
git add src/Go2_control_gateway/go2_control_gateway/web \
        src/Go2_control_gateway/test/test_web_contract.py
git commit -m "feat: add LAN robot control console"
```

### Task 10: Add deployment assets and startup integration

**Files:**

- Create: `src/Go2_control_gateway/systemd/go2-cmd-gateway.service`
- Create: `src/Go2_control_gateway/systemd/go2-console.service`
- Create: `src/Go2_control_gateway/config/internal_gateway.env`
- Create: `src/Go2_control_gateway/scripts/deploy_internal_gateway.sh`
- Create: `src/Go2_control_gateway/scripts/install_external_services.sh`
- Create: `src/Go2_bringup/go2_gateway_arm.sh`
- Create: `src/Go2_bringup/go2_gateway_disarm.sh`
- Create: `src/Go2_bringup/go2_gateway_status.sh`
- Modify: `src/Go2_bringup/run_nav2.sh`
- Modify: `src/Go2_bringup/run_keyboard_teleop.sh`
- Modify: `src/Go2_bringup/run_robot_web.sh`
- Create: `src/Go2_control_gateway/test/test_deployment_contract.py`

**Step 1: Write failing deployment-contract tests**

Assert:

- internal service binds `eth0`/`192.168.123.18` and restarts locked;
- external sender targets the correct IP/ports;
- console service runs as `nvidia`, not root;
- scripts never contain plaintext passwords;
- direct DDS launch remains present;
- normal Nav2 launch selects the UDP sender;
- shutdown scripts Disarm before stopping services;
- rosbridge binds loopback if it is started.

**Step 2: Verify RED**

```powershell
python -m pytest src/Go2_control_gateway/test/test_deployment_contract.py -q
```

Expected: FAIL because deployment assets are missing.

**Step 3: Implement the assets**

Use `EnvironmentFile` for addresses/ports, `Restart=on-failure`, bounded restart
delays, and explicit dependency ordering. The internal daemon itself—not
systemd—must own the StopMove-on-exit behavior.

**Step 4: Verify GREEN and shell syntax**

```powershell
python -m pytest src/Go2_control_gateway/test/test_deployment_contract.py -q
bash -n src/Go2_control_gateway/scripts/deploy_internal_gateway.sh
bash -n src/Go2_control_gateway/scripts/install_external_services.sh
bash -n src/Go2_bringup/go2_gateway_arm.sh
bash -n src/Go2_bringup/go2_gateway_disarm.sh
bash -n src/Go2_bringup/go2_gateway_status.sh
```

Expected: PASS.

**Step 5: Commit**

```bash
git add src/Go2_control_gateway src/Go2_bringup
git commit -m "feat: integrate gateway deployment and startup"
```

### Task 11: Update repository documentation

**Files:**

- Modify: `README.md`
- Modify: `src/Go2_bringup/README.md`
- Create: `docs/go2-control-network-and-console.md`
- Create: `docs/go2-control-acceptance-checklist.md`
- Create: `src/Go2_control_gateway/README.md`
- Create: `src/Go2_control_gateway/test/test_documentation_contract.py`

**Step 1: Write the failing documentation contract**

Assert that documentation includes:

- all device IPs and subnets;
- `eth0`, `eth1`, `wlan0` responsibilities;
- exact external → internal → lower-controller architecture;
- UDP/Arm/fail-closed behavior;
- console login/manual/Nav2 interlock;
- normal operation, shutdown, recovery and rollback commands.

**Step 2: Verify RED**

```powershell
python -m pytest src/Go2_control_gateway/test/test_documentation_contract.py -q
```

Expected: FAIL because the delivery documentation is absent.

**Step 3: Write the documentation**

Keep tested radar/navigation instructions intact and clearly mark the direct DDS
bridge as diagnostic-only.

**Step 4: Verify GREEN**

Repeat Step 2 and run `git diff --check`.

Expected: PASS.

**Step 5: Commit**

```bash
git add README.md src/Go2_bringup/README.md \
        src/Go2_control_gateway/README.md docs
git commit -m "docs: document Go2 control network and console"
```

### Task 12: Run offline verification

**Files:**

- Modify only files required to fix discovered test failures.

**Step 1: Run the complete Python suite**

```powershell
python -m pytest src/Go2_control_gateway/test -q
```

**Step 2: Run syntax and static checks**

```powershell
python -m compileall -q src/Go2_control_gateway/go2_control_gateway
git diff --check
git status --short
```

**Step 3: Review requirements line by line**

Compare the implementation against
`docs/plans/2026-07-28-go2-udp-control-gateway-design.md` and record any
hardware-only items as pending rather than claiming completion.

**Step 4: Commit fixes if required**

```bash
git add <only-the-fixed-files>
git commit -m "test: complete offline gateway verification"
```

### Task 13: Deploy and run no-motion hardware verification

**Prerequisite:** Both boards are powered; no physical movement is authorized.

**Step 1: Build the ROS package on the external Jetson**

```bash
cd /home/nvidia/Go2_Nav_ws
source /opt/ros/foxy/setup.bash
colcon build --symlink-install --packages-select go2_control_gateway
```

Expected: exit 0.

**Step 2: Build and install the internal daemon**

Run the deployment script through the external-to-internal SSH route. Verify
binary linkage before enabling the service.

**Step 3: Install services but keep Arm false**

Verify:

- both services active;
- internal status LOCKED;
- UDP heartbeat/ACK at 20 Hz;
- source-IP filtering;
- Arm token handshake using a dry-run SDK mode first;
- watchdog transitions to LOCKED when the sender service is stopped;
- service restarts remain LOCKED.

**Step 4: Verify console**

Set the operator password, log in, verify single-control lease, state fields,
Arm confirmation UI and Nav2/manual interlock. Do not confirm physical Arm until
the user is present.

**Step 5: Save evidence**

Record command outputs and screenshots in
`docs/go2-control-acceptance-checklist.md`.

### Task 14: Perform authorized physical acceptance tests

**Prerequisite:** User confirms robot is off the charger, standing, and the area
is clear.

**Step 1: Arm/Disarm without nonzero velocity**

Confirm `BalanceStand=0`, ARMED ACK, zero velocity, and successful Disarm.

**Step 2: Low-speed manual test**

Use hold-to-run at `0.10 m/s` for a short bounded interval, release, and verify
StopMove/zero velocity.

**Step 3: Fail-closed link test**

At zero/very low speed in a clear area, interrupt the external sender and verify
StopMove plus automatic Disarm within 0.5 s. Confirm old Arm token cannot re-arm.

**Step 4: Nav2 chain test**

Arm explicitly, send a short navigation goal, verify `/cmd_vel` →
UDP → internal SportClient movement, cancel the goal, and verify stop.

**Step 5: Update acceptance record**

Record actual timing, SDK codes, state transitions, distance and observed
behavior. Do not substitute theoretical values.

### Task 15: Update the existing Feishu document

**Prerequisite:** User supplies the Feishu document URL and the browser has an
authenticated session.

**Step 1: Open and inspect the current document**

Preserve existing validated radar/navigation content and identify the correct
sections for revision.

**Step 2: Update required content**

Include:

- IP and static route settings;
- `eth0`/`eth1`/`wlan0` descriptions;
- external → internal → lower-controller diagram;
- current UDP/Arm/fail-closed control chain;
- LAN Web console login, speed/manual control and Nav2 interlock;
- startup, shutdown, failure recovery and rollback;
- measured acceptance-test evidence.

**Step 3: Verify the document**

Re-open the edited sections, check headings/tables/diagrams and confirm no
credentials, password hashes, tokens or private contact information were added.

**Step 4: Record the updated document link**

Add the Feishu link and update date to the local acceptance checklist.
