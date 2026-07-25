# FAST-LIVO2 Foxy Deployment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build and validate an isolated ROS 2 Foxy FAST-LIVO2 workspace for the connected MID-360S and D435i without modifying the existing FAST-LIO2/Nav2 workspaces, while preserving a documented path to ROS 2 Humble.

**Architecture:** A new `/home/nvidia/fastlivo2_ws` colcon workspace owns the FAST-LIVO2 ROS 2 port, Vikit, RealSense wrapper, bringup package, compatibility patches, configuration, maps, and logs. The existing Livox driver and PTP implementation are consumed read-only at runtime. Common sensor configuration is separated from Foxy compatibility code so the latter can be removed during a future Humble rebuild.

**Tech Stack:** Ubuntu 20.04, ROS 2 Foxy, colcon, CMake, C++17, Python 3.8, pytest, FAST-LIVO2 ROS 2 port, Livox ROS Driver 2, librealsense RSUSB backend, RealSense ROS 2 wrapper, Sophus, Vikit, linuxptp.

---

### Task 1: Capture the Isolation Baseline

**Files:**
- Create: `/home/nvidia/fastlivo2_ws/logs/baseline/system.txt`
- Create: `/home/nvidia/fastlivo2_ws/logs/baseline/existing-workspaces.sha256`
- Create: `/home/nvidia/fastlivo2_ws/logs/baseline/existing-git-status.txt`

**Step 1: Verify the target does not exist**

Run:

```bash
test ! -e /home/nvidia/fastlivo2_ws
```

Expected: exit 0.

**Step 2: Record existing workspace state**

Record:

```bash
uname -a
cat /etc/os-release
printenv ROS_DISTRO
git -C /home/nvidia/ws_fastlio2/src/FAST_LIO_ROS2 status --short
git -C /home/nvidia/ws_fastlio2/src/FAST_LIO_ROS2 diff
git -C /home/nvidia/ws_Livox/src/livox_ros_driver2 status --short
git -C /home/nvidia/ws_Livox/src/livox_ros_driver2 diff
git -C /home/nvidia/Go2_Nav_ws status --short
```

Expected: capture the existing local modifications without changing them.

**Step 3: Create only the new workspace root**

Create:

```text
/home/nvidia/fastlivo2_ws/
├── compat/foxy/
├── config/common/
├── config/foxy/
├── config/humble/
├── deps/
├── logs/baseline/
├── manifests/
├── maps/
├── scripts/
└── src/
```

**Step 4: Save hashes of protected source trees**

Hash tracked files from:

```text
/home/nvidia/ws_fastlio2/src/FAST_LIO_ROS2
/home/nvidia/ws_Livox/src/livox_ros_driver2
/home/nvidia/Go2_Nav_ws
```

Exclude build, install, log, maps, `.git`, and generated caches.

**Step 5: Verify no protected file changed**

Run the same status commands from Step 2.

Expected: identical output.

### Task 2: Add the Bringup Package Tests First

**Files:**
- Create: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/package.xml`
- Create: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/setup.py`
- Create: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/setup.cfg`
- Create: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/resource/fastlivo2_bringup`
- Create: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/fastlivo2_bringup/__init__.py`
- Test: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/test/test_preflight.py`
- Test: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/test/test_timestamp_stats.py`

**Step 1: Write failing preflight tests**

Cover:

```python
def test_rejects_existing_fastlio_process():
    result = inspect_processes(["/opt/ros/foxy/bin/fast_lio"])
    assert result.safe is False


def test_does_not_reject_unrelated_process():
    result = inspect_processes(["/usr/bin/firefox"])
    assert result.safe is True


def test_requires_mid360_address():
    result = inspect_network(["192.168.1.5/24"], reachable=False)
    assert "192.168.1.158" in result.errors
```

**Step 2: Write failing timestamp-statistics tests**

Cover:

```python
def test_detects_backward_timestamp():
    stats = TimestampStats()
    stats.add(10.0)
    stats.add(9.9)
    assert stats.backward_jumps == 1


def test_reports_percentiles():
    stats = DeltaStats([0.001, 0.002, 0.004])
    assert stats.max_seconds == 0.004
```

**Step 3: Run the tests and confirm failure**

Run:

```bash
cd /home/nvidia/fastlivo2_ws
python3 -m pytest src/fastlivo2_bringup/test -v
```

Expected: fail because the implementation modules do not exist.

**Step 4: Commit the failing tests in the new source repository**

Initialize the bringup package as its own Git repository and commit only its
source and tests.

### Task 3: Implement Isolation Preflight and Timestamp Utilities

**Files:**
- Create: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/fastlivo2_bringup/preflight.py`
- Create: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/fastlivo2_bringup/timestamp_stats.py`
- Create: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/fastlivo2_bringup/preflight_cli.py`
- Modify: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/setup.py`

**Step 1: Implement the minimum preflight logic**

The preflight must check:

- `/opt/ros/foxy/setup.bash` exists;
- `/home/nvidia/ws_Livox/install/setup.bash` exists;
- `eth0` has `192.168.1.5/24`;
- `192.168.1.158` responds;
- the D435i USB ID `8086:0b3a` is present;
- no Livox publisher, FAST-LIO, FAST-LIVO2, or Nav2 process is active;
- output paths resolve under `/home/nvidia/fastlivo2_ws`.

It must report errors and exit nonzero. It must never kill a process.

**Step 2: Implement timestamp statistics**

Track:

- message count;
- first and last timestamp;
- backward jumps;
- minimum, median, p95, and maximum deltas;
- stale intervals;
- camera-to-LiDAR nearest-neighbor delta.

**Step 3: Run unit tests**

Run:

```bash
python3 -m pytest src/fastlivo2_bringup/test -v
```

Expected: all pass.

**Step 4: Run the CLI against the idle Jetson**

Expected: sensor/network checks pass and no protected process is stopped.

**Step 5: Commit**

Commit the implementation and passing tests in the bringup repository.

### Task 4: Pin Upstream Source and Dependency Manifests

**Files:**
- Create: `/home/nvidia/fastlivo2_ws/manifests/foxy.repos`
- Create: `/home/nvidia/fastlivo2_ws/manifests/humble.repos`
- Create: `/home/nvidia/fastlivo2_ws/manifests/versions.lock`
- Create: `/home/nvidia/fastlivo2_ws/compat/foxy/README.md`
- Create: `/home/nvidia/fastlivo2_ws/compat/foxy/*.patch`

**Step 1: Pin the Humble upstream**

Use the ROS 2 Humble FAST-LIVO2 port as the algorithm baseline. Record the
exact repository URL, branch, and commit before modifying it.

**Step 2: Pin the matching Vikit port**

Record its exact URL and commit in both manifests.

**Step 3: Pin Foxy RealSense components**

Use a Foxy-compatible RealSense ROS 2 wrapper and matching librealsense
release. Record both revisions.

**Step 4: Create the Humble manifest**

The Humble manifest must use the same algorithm and common configuration but
may select newer RealSense and Vikit revisions.

**Step 5: Verify reproducibility**

Run:

```bash
vcs validate < manifests/foxy.repos
vcs validate < manifests/humble.repos
```

Expected: both manifests validate.

**Step 6: Commit manifests and compatibility documentation**

Do not commit generated build or install directories.

### Task 5: Build Private Native Dependencies

**Files:**
- Create: `/home/nvidia/fastlivo2_ws/scripts/build_deps.sh`
- Create: `/home/nvidia/fastlivo2_ws/logs/build/deps.log`

**Step 1: Inventory apt dependencies**

Use `dpkg-query` and `rosdep check` without upgrading or removing packages.

**Step 2: Install only missing additive packages**

Install the minimum Foxy/PCL/OpenCV/Eigen/image transport/build tools required.
Do not run a distribution upgrade.

**Step 3: Build Sophus into a private prefix**

Install under:

```text
/home/nvidia/fastlivo2_ws/deps/sophus/install
```

Do not install it under `/usr/local`.

**Step 4: Build librealsense with RSUSB**

Install under:

```text
/home/nvidia/fastlivo2_ws/deps/librealsense/install
```

Use the RSUSB/libuvc backend and do not patch the Jetson kernel.

**Step 5: Verify the private binaries**

Run the private `rs-enumerate-devices`.

Expected: identify the connected D435i, serial number, firmware, stream
profiles, and timestamp capabilities.

**Step 6: Re-run protected workspace hashes**

Expected: no protected source file changed.

### Task 6: Establish and Fix the Foxy Build

**Files:**
- Modify: `/home/nvidia/fastlivo2_ws/src/fast_livo2/**`
- Modify: `/home/nvidia/fastlivo2_ws/src/rpg_vikit/**`
- Create: `/home/nvidia/fastlivo2_ws/compat/foxy/*.patch`
- Create: `/home/nvidia/fastlivo2_ws/scripts/build_foxy.sh`
- Create: `/home/nvidia/fastlivo2_ws/logs/build/foxy-initial.log`
- Create: `/home/nvidia/fastlivo2_ws/logs/build/foxy-final.log`

**Step 1: Run an unmodified upstream build**

Run:

```bash
source /opt/ros/foxy/setup.bash
source /home/nvidia/ws_Livox/install/setup.bash
export CMAKE_PREFIX_PATH="/home/nvidia/fastlivo2_ws/deps/sophus/install:/home/nvidia/fastlivo2_ws/deps/librealsense/install:${CMAKE_PREFIX_PATH}"
cd /home/nvidia/fastlivo2_ws
colcon build --event-handlers console_direct+
```

Expected: record the actual Foxy incompatibilities before patching.

**Step 2: Form one compatibility hypothesis per failure**

Typical candidates include:

- Humble-only `rclcpp` callback types;
- QoS constructor differences;
- parameter declaration APIs;
- CMake package name differences;
- Vikit parameter access;
- Sophus API/version assumptions.

Patch only confirmed incompatibilities.

**Step 3: Add each compatibility change as a separate patch**

Each patch file documents:

- upstream commit;
- failing compiler output;
- minimal code change;
- Foxy verification command;
- whether it is omitted on Humble.

**Step 4: Build from clean directories**

Run:

```bash
rm -rf /home/nvidia/fastlivo2_ws/build \
       /home/nvidia/fastlivo2_ws/install \
       /home/nvidia/fastlivo2_ws/log
/home/nvidia/fastlivo2_ws/scripts/build_foxy.sh
```

The delete targets must be resolved and verified under
`/home/nvidia/fastlivo2_ws` before removal.

Expected: build exits 0.

**Step 5: Export and verify patches**

Verify a fresh checkout at the pinned commit plus the saved patches produces
the same successful build.

### Task 7: Build the RealSense Foxy Wrapper

**Files:**
- Modify: `/home/nvidia/fastlivo2_ws/manifests/foxy.repos`
- Create: `/home/nvidia/fastlivo2_ws/config/foxy/realsense.yaml`
- Create: `/home/nvidia/fastlivo2_ws/logs/build/realsense.log`

**Step 1: Build against private librealsense**

Use `CMAKE_PREFIX_PATH` and `LD_LIBRARY_PATH` scoped to the build and launch
scripts.

**Step 2: Start only the D435i color stream**

Initial settings:

```yaml
enable_color: true
enable_depth: false
enable_infra1: false
enable_infra2: false
enable_accel: false
enable_gyro: false
enable_sync: true
global_time_enabled: true
color_width: 640
color_height: 480
color_fps: 15
```

Translate parameter names in the Foxy wrapper adapter if the pinned release
uses module-qualified names.

**Step 3: Verify camera topics**

Check:

```text
/fastlivo2/camera/color/image_raw
/fastlivo2/camera/color/camera_info
/fastlivo2/camera/color/metadata
```

Expected: stable 15 Hz image stream, valid camera matrix, no backward
timestamps.

**Step 4: Save device metadata**

Record serial number, firmware, USB connection speed, stream profile, and
timestamp domain under `logs/hardware/`.

### Task 8: Add Common Sensor Configuration and Launch Files

**Files:**
- Create: `/home/nvidia/fastlivo2_ws/config/common/mid360_d435i.yaml`
- Create: `/home/nvidia/fastlivo2_ws/config/common/calibration.yaml`
- Create: `/home/nvidia/fastlivo2_ws/config/foxy/topics.yaml`
- Create: `/home/nvidia/fastlivo2_ws/config/humble/topics.yaml`
- Create: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/launch/sensors.launch.py`
- Create: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/launch/mapping.launch.py`
- Test: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/test/test_config.py`

**Step 1: Write failing configuration tests**

Verify:

- host IP is `192.168.1.5`;
- LiDAR IP is `192.168.1.158`;
- MID-360S rate is 10 Hz;
- camera starts at 640x480x15;
- maps resolve under the new workspace;
- visual fusion defaults to disabled;
- calibration placeholders cannot silently enable visual fusion.

**Step 2: Run tests and confirm failure**

Expected: fail because configuration files do not exist.

**Step 3: Implement common configuration**

Copy reference values only where measured. Mark LiDAR-camera extrinsics and
residual temporal offset as uncalibrated.

**Step 4: Implement launch wrappers**

The launcher must:

- run preflight first;
- source the existing Livox install at runtime;
- use `/fastlivo2` namespace;
- select LIO-only or LIVO mode explicitly;
- refuse LIVO mode if calibration is incomplete;
- never start a duplicate Livox publisher.

**Step 5: Run tests**

Expected: all pass.

### Task 9: Validate the Existing Software-PTP Time Chain

**Files:**
- Create: `/home/nvidia/fastlivo2_ws/scripts/verify_time_sync.sh`
- Create: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/fastlivo2_bringup/timestamp_monitor.py`
- Test: `/home/nvidia/fastlivo2_ws/src/fastlivo2_bringup/test/test_timestamp_monitor.py`
- Create: `/home/nvidia/fastlivo2_ws/logs/time-sync/`

**Step 1: Write timestamp-monitor tests**

Test synthetic Livox and camera timestamps for:

- common epoch;
- backward jumps;
- constant offset;
- jitter;
- dropped frames.

**Step 2: Implement the ROS timestamp monitor**

Subscribe to Livox custom messages, Livox IMU, D435i RGB, and camera metadata.
Do not rewrite message timestamps.

**Step 3: Validate the PTP environment read-only**

Verify:

- `eth0` software timestamp capabilities;
- no PHC is present;
- Jetson system clock state;
- MID-360S reachability;
- PTP process state.

**Step 4: Run a bounded PTP validation**

Use the existing PTP script as the reference implementation. During the test:

- do not install a second service;
- use NTP dry-run or skip NTP to avoid stepping system time;
- start software-timestamp `ptp4l` only while no existing PTP master is active;
- capture Announce, Sync, Follow_Up, Delay_Req, and Delay_Resp evidence;
- stop only the test-owned process.

**Step 5: Start sensors and collect timestamp statistics**

Expected:

- MID-360S LiDAR and IMU use the Jetson/PTP epoch;
- D435i Global Time publishes in the Jetson clock domain;
- no backward jumps;
- camera-to-LiDAR delta distribution is recorded.

Do not call the chain synchronized if only the PTP master process is running.

### Task 10: Validate FAST-LIVO2 in LIO Mode

**Files:**
- Create: `/home/nvidia/fastlivo2_ws/logs/runtime/lio.log`
- Create: `/home/nvidia/fastlivo2_ws/logs/runtime/lio-topics.txt`
- Create: `/home/nvidia/fastlivo2_ws/maps/lio-smoke-test.pcd`

**Step 1: Run preflight**

Expected: pass while the old stack is stopped.

**Step 2: Start the existing Livox driver**

Use the existing installed workspace and MID-360S configuration without
editing it.

**Step 3: Start new FAST-LIVO2 with visual fusion disabled**

Expected topics:

```text
/fastlivo2/odometry
/fastlivo2/cloud_registered
/fastlivo2/path
```

**Step 4: Verify rates and finite values**

Check topic rates, NaN/Inf values, queue growth, frame IDs, and timestamps.

**Step 5: Save a bounded smoke-test map**

Expected: valid non-empty PCD under the new workspace.

**Step 6: Stop only test-owned processes**

Expected: no new ROS/Livox process remains.

### Task 11: Prepare Calibration-Gated LIVO Mode

**Files:**
- Modify: `/home/nvidia/fastlivo2_ws/config/common/calibration.yaml`
- Create: `/home/nvidia/fastlivo2_ws/scripts/export_d435i_intrinsics.sh`
- Create: `/home/nvidia/fastlivo2_ws/scripts/check_calibration.sh`
- Create: `/home/nvidia/fastlivo2_ws/docs/calibration.md`

**Step 1: Export D435i RGB intrinsics**

Capture the camera matrix and distortion model from `camera_info` for the exact
640x480 stream.

**Step 2: Preserve LiDAR-IMU reference values**

Copy the existing measured/reference values with provenance. Do not claim they
are LiDAR-camera extrinsics.

**Step 3: Gate visual fusion**

`check_calibration.sh` must fail until a valid MID-360S-to-D435i transform and
residual time offset are present.

**Step 4: Document the FAST-Calib procedure**

Provide exact input topics and expected output mapping into
`calibration.yaml`.

**Step 5: Do not run uncalibrated LIVO**

If physical calibration cannot be completed remotely, report LIO and camera
validation as complete while leaving visual fusion deliberately disabled.

### Task 12: Performance and Thermal Validation

**Files:**
- Create: `/home/nvidia/fastlivo2_ws/scripts/benchmark.sh`
- Create: `/home/nvidia/fastlivo2_ws/logs/benchmark/`

**Step 1: Run a 10-minute baseline**

Settings:

- Jetson 25 W mode;
- MID-360S 10 Hz;
- D435i RGB 640x480x15;
- no depth/infrared/RealSense IMU;
- no local RViz.

**Step 2: Record system metrics**

Record:

- `tegrastats`;
- FAST-LIVO2 resident memory;
- CPU per core;
- per-frame processing time;
- message rates;
- dropped frames;
- timestamp jitter;
- thermal throttling.

**Step 3: Evaluate acceptance**

Pass when:

- processing remains below 100 ms per LiDAR frame;
- queues do not grow without bound;
- no timestamp jumps occur;
- memory remains bounded;
- no thermal throttling is observed.

**Step 4: Test 30 Hz color only if 15 Hz passes**

Keep 15 Hz as the default unless 30 Hz has adequate sustained margin.

### Task 13: Verify No Regression to Existing FAST-LIO2/Nav2

**Files:**
- Create: `/home/nvidia/fastlivo2_ws/logs/final/protected-workspaces.sha256`
- Create: `/home/nvidia/fastlivo2_ws/logs/final/existing-git-status.txt`
- Create: `/home/nvidia/fastlivo2_ws/logs/final/readiness.txt`

**Step 1: Stop the new stack**

Verify no test-owned process remains.

**Step 2: Recompute protected source hashes**

Expected: match Task 1.

**Step 3: Compare Git status and diffs**

Expected: all pre-existing modifications remain exactly as captured; no new
modification appears in protected workspaces.

**Step 4: Run the existing readiness checks**

Use the current Go2 readiness script without changing configuration.

Expected: the existing FAST-LIO2/Nav2 installation remains startable.

**Step 5: Write the deployment report**

Report:

- pinned revisions;
- build results;
- sensor evidence;
- timestamp evidence;
- LIO result;
- calibration blocker, if any;
- performance data;
- protected-workspace comparison;
- Foxy-to-Humble migration instructions.
