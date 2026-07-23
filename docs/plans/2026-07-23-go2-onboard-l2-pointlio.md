# Go2 Onboard L2 Point-LIO ROS2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Install a pinned Point-LIO ROS2 source tree in an independent Jetson workspace and provide safe, reproducible Go2 L2 launch, RViz2, recording, monitoring, and documentation assets.

**Architecture:** Keep third-party GPL source under `/home/nvidia/ws_pointlio2` and keep only provenance, configuration, compatibility patches, launch/record tools, tests, and documentation in `Go2_Nav_ws`. Subscribe to the Go2-provided `/utlidar/cloud` and `/utlidar/imu` topics, use the Unitree L2-specific Point-LIO preprocessing path, and never include a robot motion publisher.

**Tech Stack:** Ubuntu 20.04, ROS2 Foxy, CycloneDDS 0.10.2, C++17, colcon, PCL, Eigen3, Python 3 `unittest`, Bash, RViz2, rosbag2.

---

### Task 1: Add the pinned source manifest

**Files:**
- Create: `scripts/go2_pointlio/source.lock`
- Create: `scripts/go2_pointlio/tests/__init__.py`
- Create: `scripts/go2_pointlio/tests/test_pointlio_assets.py`

**Step 1: Write the failing source-manifest test**

Add a `PointLioSourceLockTest` that parses `source.lock` as `KEY=VALUE` lines and
asserts:

```python
self.assertEqual(
    values["POINT_LIO_REPOSITORY"],
    "https://github.com/dfloreaa/point_lio_ros2.git",
)
self.assertEqual(
    values["POINT_LIO_COMMIT"],
    "a8e2d0d5090af97ead8dd4fac3d37cf3dbb33ff7",
)
self.assertEqual(values["POINT_LIO_LICENSE"], "GPL-2.0")
self.assertEqual(values["POINT_LIO_WORKSPACE"], "/home/nvidia/ws_pointlio2")
self.assertEqual(
    values["UNITREE_REFERENCE_COMMIT"],
    "18ed5976d8fab2bd8a5148c26a40692bd3c0dc91",
)
self.assertEqual(
    values["UNITREE_L2_SDK_COMMIT"],
    "0e3c51f512e6b8ff60b8c32f160b412cb48445c2",
)
```

Also assert that the manifest does not point inside
`/home/nvidia/Go2_Nav_ws/src`.

**Step 2: Run the test and verify RED**

Run:

```bash
python3 -m unittest -v \
  scripts.go2_pointlio.tests.test_pointlio_assets.PointLioSourceLockTest
```

Expected: FAIL because `scripts/go2_pointlio/source.lock` does not exist.

**Step 3: Add the minimal manifest**

Create:

```dotenv
POINT_LIO_REPOSITORY=https://github.com/dfloreaa/point_lio_ros2.git
POINT_LIO_COMMIT=a8e2d0d5090af97ead8dd4fac3d37cf3dbb33ff7
POINT_LIO_LICENSE=GPL-2.0
POINT_LIO_WORKSPACE=/home/nvidia/ws_pointlio2
UNITREE_REFERENCE_REPOSITORY=https://github.com/unitreerobotics/point_lio_unilidar.git
UNITREE_REFERENCE_COMMIT=18ed5976d8fab2bd8a5148c26a40692bd3c0dc91
UNITREE_L2_SDK_REPOSITORY=https://github.com/unitreerobotics/unilidar_sdk2.git
UNITREE_L2_SDK_COMMIT=0e3c51f512e6b8ff60b8c32f160b412cb48445c2
```

**Step 4: Run the test and verify GREEN**

Run the command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/go2_pointlio/source.lock \
  scripts/go2_pointlio/tests/__init__.py \
  scripts/go2_pointlio/tests/test_pointlio_assets.py
git commit -m "test: pin Go2 Point-LIO source provenance"
```

### Task 2: Add the Unitree L2 Point-LIO configuration

**Files:**
- Create: `scripts/go2_pointlio/config/go2_l2.yaml`
- Modify: `scripts/go2_pointlio/tests/test_pointlio_assets.py`

**Step 1: Write failing configuration tests**

Add tests that load `go2_l2.yaml` with `yaml.safe_load()` and assert:

```python
params = document["/**"]["ros__parameters"]
self.assertEqual(params["common"]["lid_topic"], "/utlidar/cloud")
self.assertEqual(params["common"]["imu_topic"], "/utlidar/imu")
self.assertEqual(params["preprocess"]["lidar_type"], 5)
self.assertEqual(params["preprocess"]["scan_line"], 18)
self.assertEqual(params["preprocess"]["timestamp_unit"], 0)
self.assertEqual(params["preprocess"]["blind"], 0.5)
self.assertTrue(params["mapping"]["imu_en"])
self.assertFalse(params["mapping"]["extrinsic_est_en"])
self.assertEqual(params["mapping"]["acc_norm"], 9.81)
self.assertEqual(
    params["mapping"]["extrinsic_T"],
    [0.007698, 0.014655, -0.00667],
)
self.assertEqual(
    params["mapping"]["extrinsic_R"],
    [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
)
self.assertFalse(params["pcd_save"]["pcd_save_en"])
```

Assert the parameters normally supplied inline by
`mapping_unilidar_l2.launch.py` are also present:

```python
self.assertFalse(params["use_imu_as_input"])
self.assertTrue(params["prop_at_freq_of_imu"])
self.assertTrue(params["check_satu"])
self.assertEqual(params["point_filter_num"], 1)
self.assertEqual(params["filter_size_surf"], 0.1)
self.assertEqual(params["filter_size_map"], 0.1)
```

**Step 2: Run the tests and verify RED**

```bash
python3 -m unittest -v \
  scripts.go2_pointlio.tests.test_pointlio_assets.PointLioConfigTest
```

Expected: FAIL because the config does not exist.

**Step 3: Add the minimal configuration**

Copy the pinned upstream `config/unilidar_l2.yaml`, retain its L2 preprocessing,
IMU saturation, covariance, gravity, and extrinsic values, then:

- change topics to `/utlidar/cloud` and `/utlidar/imu`;
- merge the pinned upstream L2 launch parameters into the YAML;
- set `runtime_pos_log_enable: false`;
- set `pcd_save_en: false`;
- add source/commit comments at the top.

Do not tune more than those integration fields.

**Step 4: Run the tests and verify GREEN**

Run the command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/go2_pointlio/config/go2_l2.yaml \
  scripts/go2_pointlio/tests/test_pointlio_assets.py
git commit -m "feat: add Unitree L2 Point-LIO configuration"
```

### Task 3: Add a reproducible independent-workspace installer

**Files:**
- Create: `scripts/go2_pointlio/install_pointlio2.sh`
- Create: `scripts/go2_pointlio/patches/README.md`
- Modify: `scripts/go2_pointlio/tests/test_pointlio_assets.py`

**Step 1: Write failing installer tests**

Add tests that read the installer text and assert:

```python
self.assertIn("source.lock", source)
self.assertIn('POINT_LIO_WORKSPACE="/home/nvidia/ws_pointlio2"', source)
self.assertIn('src/point_lio_ros2', source)
self.assertIn('git checkout --detach "${POINT_LIO_COMMIT}"', source)
self.assertIn('/opt/ros/foxy/setup.bash', source)
self.assertIn('/home/nvidia/ws_Livox/install/setup.bash', source)
self.assertIn('colcon build', source)
self.assertNotIn('/home/nvidia/Go2_Nav_ws/src/point_lio', source)
```

Also assert that the script refuses to overwrite a source tree whose configured
remote differs from `POINT_LIO_REPOSITORY`.

**Step 2: Run the installer tests and verify RED**

```bash
python3 -m unittest -v \
  scripts.go2_pointlio.tests.test_pointlio_assets.PointLioInstallerTest
```

Expected: FAIL because the installer does not exist.

**Step 3: Add the installer**

Implement a Bash script with:

```bash
#!/usr/bin/env bash
set -euo pipefail
```

Required behavior:

1. source `source.lock`;
2. require the exact workspace `/home/nvidia/ws_pointlio2`;
3. clone only when `src/point_lio_ros2/.git` is absent;
4. validate the existing `origin` URL before using an existing checkout;
5. fetch the pinned commit and checkout detached;
6. fail on a dirty third-party source tree;
7. apply sorted `patches/*.patch` only when present;
8. source Foxy and Livox setup with `set +u` around third-party setup files;
9. build only the `point_lio` package with:

```bash
colcon build --symlink-install --packages-select point_lio
```

10. print the final source commit and package prefix.

The script must not delete `build`, `install`, `log`, or source trees.

**Step 4: Run syntax and unit tests**

```bash
bash -n scripts/go2_pointlio/install_pointlio2.sh
python3 -m unittest -v \
  scripts.go2_pointlio.tests.test_pointlio_assets.PointLioInstallerTest
```

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/go2_pointlio/install_pointlio2.sh \
  scripts/go2_pointlio/patches/README.md \
  scripts/go2_pointlio/tests/test_pointlio_assets.py
git commit -m "feat: add pinned Point-LIO workspace installer"
```

### Task 4: Add the guarded Point-LIO launcher

**Files:**
- Create: `scripts/go2_pointlio/run_pointlio_l2.sh`
- Modify: `scripts/go2_pointlio/tests/test_pointlio_assets.py`

**Step 1: Write failing launcher tests**

Assert the launcher:

- defaults `UNITREE_INTERFACE` to `eth0`;
- requires `/home/nvidia/ws_pointlio2/install/setup.bash`;
- sources Unitree ROS2, Livox, and Point-LIO setup files;
- temporarily disables nounset around Foxy/third-party setup;
- calls the existing read-only
  `scripts/go2_l2/l2_input_probe.py`;
- supports `--probe-only` and `--skip-probe`;
- starts `point_lio pointlio_mapping` with
  `config/go2_l2.yaml`;
- supports `RVIZ=true`;
- installs traps that stop only its own Point-LIO/RViz children;
- contains none of:

```python
forbidden = [
    "sportmoderequest",
    "api/sport/request",
    "Move(",
    "velocity_command",
    "cmd_vel",
]
```

**Step 2: Run launcher tests and verify RED**

```bash
python3 -m unittest -v \
  scripts.go2_pointlio.tests.test_pointlio_assets.PointLioLauncherTest
```

Expected: FAIL because the launcher does not exist.

**Step 3: Add the launcher**

Implement:

```text
run_pointlio_l2.sh [--probe-only] [--skip-probe]
```

The normal path must:

1. resolve the repository root from `BASH_SOURCE`;
2. load the three ROS environments safely;
3. run the six-second L2 probe;
4. start:

```bash
ros2 run point_lio pointlio_mapping --ros-args \
  --params-file "${CONFIG_FILE}"
```

5. optionally start:

```bash
rviz2 -d "${RVIZ_CONFIG}"
```

6. keep Point-LIO in the foreground lifecycle;
7. on `INT`/`TERM` signal only the recorded child PIDs;
8. return nonzero if Point-LIO exits unexpectedly.

Do not use `pkill`, `killall`, or broad process matching.

**Step 4: Run syntax and unit tests**

```bash
bash -n scripts/go2_pointlio/run_pointlio_l2.sh
python3 -m unittest -v \
  scripts.go2_pointlio.tests.test_pointlio_assets.PointLioLauncherTest
```

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/go2_pointlio/run_pointlio_l2.sh \
  scripts/go2_pointlio/tests/test_pointlio_assets.py
git commit -m "feat: add guarded Go2 L2 Point-LIO launcher"
```

### Task 5: Add a clean RViz2 configuration

**Files:**
- Create: `scripts/go2_pointlio/rviz/go2_l2_pointlio.rviz`
- Modify: `scripts/go2_pointlio/tests/test_pointlio_assets.py`

**Step 1: Write failing RViz tests**

Assert that the config:

```python
self.assertIn("Fixed Frame: camera_init", source)
self.assertIn("Value: /cloud_registered", source)
self.assertIn("Value: /path", source)
self.assertNotIn("rviz_common/Time", source)
```

Also require a display for `/aft_mapped_to_init` and reliable/volatile QoS for
the registered cloud.

**Step 2: Run the RViz test and verify RED**

```bash
python3 -m unittest -v \
  scripts.go2_pointlio.tests.test_pointlio_assets.PointLioRvizTest
```

Expected: FAIL because the RViz config does not exist.

**Step 3: Add the RViz configuration**

Start from the pinned Point-LIO `rviz_cfg/loam_livox.rviz`, keep only:

- Grid;
- TF;
- Odometry `/aft_mapped_to_init`;
- Path `/path`;
- PointCloud2 `/cloud_registered`;

and remove the unavailable Time panel and unused navigation panels.

Set the registered cloud decay to 60 seconds for the first test. Do not use an
unbounded decay until Jetson GPU/memory usage is measured.

**Step 4: Run the test and verify GREEN**

Run the command from Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/go2_pointlio/rviz/go2_l2_pointlio.rviz \
  scripts/go2_pointlio/tests/test_pointlio_assets.py
git commit -m "feat: add Go2 Point-LIO RViz2 view"
```

### Task 6: Add diagnostic recording and odometry monitoring

**Files:**
- Create: `scripts/go2_pointlio/record_pointlio_l2.sh`
- Create: `scripts/go2_pointlio/pointlio_watchdog.py`
- Create: `scripts/go2_pointlio/tests/test_pointlio_watchdog.py`
- Modify: `scripts/go2_pointlio/tests/test_pointlio_assets.py`

**Step 1: Write failing watchdog core tests**

Design a pure function:

```python
evaluate_odom_step(
    previous,
    current,
    *,
    max_step_m=0.5,
    max_speed_mps=3.0,
    max_yaw_rate_rps=4.0,
) -> list[str]
```

Write tests for:

- normal slow forward motion returns no errors;
- a 10 m jump in 0.1 s returns displacement and speed errors;
- a timestamp regression returns an error;
- NaN position or quaternion returns an error;
- an excessive yaw-rate step returns an error.

**Step 2: Run watchdog tests and verify RED**

```bash
python3 -m unittest -v \
  scripts.go2_pointlio.tests.test_pointlio_watchdog
```

Expected: FAIL because the module does not exist.

**Step 3: Implement the pure watchdog core**

Use dataclasses or tuples for timestamp, XYZ position, and quaternion. Compute
quaternion yaw with `atan2`, wrap yaw delta to `[-pi, pi]`, and return explicit
reader-facing error strings. Do not import ROS in the pure core.

**Step 4: Run watchdog tests and verify GREEN**

Run the command from Step 2.

Expected: PASS.

**Step 5: Write failing recorder and safety-boundary tests**

Assert `record_pointlio_l2.sh`:

- records `/utlidar/cloud`, `/utlidar/imu`, `/aft_mapped_to_init`, `/path`,
  `/wirelesscontroller`, and `/lf/sportmodestate`;
- creates a timestamped directory below
  `/home/nvidia/Go2_Nav_ws/bags/go2_l2_pointlio`;
- writes a session manifest containing git/source commits and topic list;
- checks available disk before starting;
- traps only its own rosbag PID;
- contains no motion interface.

Assert the live watchdog subscribes only to input/output topics and may signal
only the explicitly supplied Point-LIO PID.

**Step 6: Run recorder tests and verify RED**

```bash
python3 -m unittest -v \
  scripts.go2_pointlio.tests.test_pointlio_assets.PointLioRecorderTest
```

Expected: FAIL because the recorder does not exist.

**Step 7: Implement recorder and live watchdog**

The recorder prints its output directory before starting and uses:

```bash
ros2 bag record --output "${SESSION_DIR}/rosbag" \
  /utlidar/cloud \
  /utlidar/imu \
  /aft_mapped_to_init \
  /path \
  /wirelesscontroller \
  /lf/sportmodestate
```

The live watchdog:

- allows an initialization grace period;
- validates finite odometry and bounded steps;
- reports source input timeout separately from odometry timeout;
- on a fatal condition writes JSON and sends `SIGINT` only to the explicit
  `--pointlio-pid`;
- never invokes Unitree motion APIs.

**Step 8: Run all new tests**

```bash
bash -n scripts/go2_pointlio/record_pointlio_l2.sh
python3 -m unittest -v \
  scripts.go2_pointlio.tests.test_pointlio_assets \
  scripts.go2_pointlio.tests.test_pointlio_watchdog
```

Expected: PASS.

**Step 9: Commit**

```bash
git add scripts/go2_pointlio/record_pointlio_l2.sh \
  scripts/go2_pointlio/pointlio_watchdog.py \
  scripts/go2_pointlio/tests
git commit -m "feat: record and monitor Go2 Point-LIO sessions"
```

### Task 7: Build the pinned upstream on Jetson and handle Foxy compatibility

**Files:**
- Conditionally create: `scripts/go2_pointlio/patches/0001-foxy-compat.patch`
- Modify: `scripts/go2_pointlio/patches/README.md`
- Modify: `scripts/go2_pointlio/tests/test_pointlio_assets.py`

**Step 1: Deploy the installer assets only**

Synchronize `scripts/go2_pointlio/source.lock`,
`install_pointlio2.sh`, and `patches/` to:

```text
/home/nvidia/Go2_Nav_ws/scripts/go2_pointlio/
```

Do not deploy a third-party source tree through SFTP.

**Step 2: Run the pinned installer**

On Jetson:

```bash
cd /home/nvidia/Go2_Nav_ws
bash scripts/go2_pointlio/install_pointlio2.sh \
  > /tmp/go2_pointlio_build.log 2>&1
```

Expected: source is checked out at
`a8e2d0d5090af97ead8dd4fac3d37cf3dbb33ff7` and `point_lio` builds.

**Step 3: If the Foxy build fails, use systematic debugging**

Invoke `@superpowers:systematic-debugging`.

For each compiler error:

1. capture the complete command and first root error;
2. compare the used ROS API against Foxy headers;
3. write a source-level or static regression test that fails against the
   unpatched checkout;
4. make the smallest compatibility change in the external checkout;
5. export only that change:

```bash
git -C /home/nvidia/ws_pointlio2/src/point_lio_ros2 diff \
  > /home/nvidia/Go2_Nav_ws/scripts/go2_pointlio/patches/0001-foxy-compat.patch
```

6. reset the external tree by recloning into a separate temporary directory,
   apply the stored patch through the installer, and rebuild.

Do not add a patch if upstream builds unmodified.

**Step 4: Verify the installed package**

```bash
set +u
source /opt/ros/foxy/setup.bash
source /home/nvidia/ws_Livox/install/setup.bash
source /home/nvidia/ws_pointlio2/install/setup.bash
set -u

ros2 pkg prefix point_lio
ros2 pkg executables point_lio
```

Expected:

```text
/home/nvidia/ws_pointlio2/install/point_lio
point_lio pointlio_mapping
```

**Step 5: Record build provenance**

Save:

- `git rev-parse HEAD`;
- `git status --short`;
- build log checksum;
- patch checksum or `no patch required`;
- ROS/PCL/Eigen/compiler versions.

**Step 6: Commit any compatibility artifacts**

If no patch was required, update `patches/README.md` with the verified result.
If a patch was required, add its regression test and checksum.

```bash
git add scripts/go2_pointlio/patches \
  scripts/go2_pointlio/tests/test_pointlio_assets.py
git commit -m "fix: support Point-LIO on ROS2 Foxy"
```

### Task 8: Deploy and run the stationary Point-LIO validation

**Files:**
- Create: `docs/go2/机载L2_Point-LIO技术手册.md`
- Create: `docs/go2/l2_pointlio验证记录_2026-07-23.md`
- Create: `scripts/go2_pointlio/README.md`
- Modify: `README.md`

**Step 1: Deploy all controlled assets**

Synchronize:

```text
scripts/go2_pointlio/
docs/go2/机载L2_Point-LIO技术手册.md
```

to `/home/nvidia/Go2_Nav_ws`, preserving executable bits for Bash and Python
entry points.

**Step 2: Run Jetson-side unit and syntax tests**

```bash
cd /home/nvidia/Go2_Nav_ws
python3 -m unittest -v \
  scripts.go2_pointlio.tests.test_pointlio_assets \
  scripts.go2_pointlio.tests.test_pointlio_watchdog
bash -n scripts/go2_pointlio/install_pointlio2.sh
bash -n scripts/go2_pointlio/run_pointlio_l2.sh
bash -n scripts/go2_pointlio/record_pointlio_l2.sh
```

Expected: all tests and syntax checks pass.

**Step 3: Run the input gate**

```bash
cd /home/nvidia/Go2_Nav_ws
UNITREE_INTERFACE=eth0 \
  bash scripts/go2_pointlio/run_pointlio_l2.sh --probe-only
```

Expected: `ready_for_fastlio2` remains `true`; the shared probe name is
historical and validates the same L2 input contract.

**Step 4: Run a 60-second stationary smoke test**

Keep the robot stationary. This step does not authorize movement.

```bash
cd /home/nvidia/Go2_Nav_ws
timeout --signal=INT --kill-after=10 70 \
  env UNITREE_INTERFACE=eth0 RVIZ=false \
  bash scripts/go2_pointlio/run_pointlio_l2.sh \
  > /tmp/go2_l2_pointlio_static.log 2>&1
```

Expected:

- Point-LIO initializes;
- `/aft_mapped_to_init`, `/cloud_registered`, and `/path` publish continuously;
- no NaN, fatal exception, matching-failure loop, or unexpected exit;
- no leftover Point-LIO process.

**Step 5: Measure stationary outputs**

During the run, sample:

```bash
ros2 topic hz /aft_mapped_to_init
ros2 topic hz /cloud_registered
ros2 topic hz /path
```

Collect the first and last odometry pose and calculate translation/yaw drift.
Record CPU, memory, and temperature.

**Step 6: Run RViz2 without movement**

From the VNC desktop:

```bash
cd /home/nvidia/Go2_Nav_ws
UNITREE_INTERFACE=eth0 RVIZ=true \
  bash scripts/go2_pointlio/run_pointlio_l2.sh
```

Verify:

- Fixed Frame is correct;
- registered cloud, path, and odometry are green;
- there is no missing Time-panel error;
- stopping the terminal closes only Point-LIO and its RViz child.

**Step 7: Document results**

The technical manual must include:

- all upstream URLs and commits;
- GPL boundary and future-repository migration;
- Jetson environment and dependencies;
- build and patch procedure;
- L2 parameters and topic contract;
- launch, RViz2, recording, and recovery commands;
- FAST-LIO2 dynamic failure and why Point-LIO was selected;
- explicit no-motion safety boundary.

The dated validation record must include raw commands, measured rates/drift,
log paths, checksums, and unresolved items.

**Step 8: Run local regression tests**

```bash
python3 -m unittest -v \
  scripts.go2_pointlio.tests.test_pointlio_assets \
  scripts.go2_pointlio.tests.test_pointlio_watchdog \
  scripts.go2_l2.tests.test_l2_fastlio_assets \
  scripts.go2_l2.tests.test_l2_input_probe \
  scripts.go2.tests.test_go2_closed_loop_motion
git diff --check
```

Expected: all tests pass and `git diff --check` is clean.

**Step 9: Commit**

```bash
git add README.md scripts/go2_pointlio docs/go2
git commit -m "docs: record Go2 L2 Point-LIO deployment"
```

### Task 9: Prepare, but do not execute, the dynamic validation

**Files:**
- Modify: `docs/go2/机载L2_Point-LIO技术手册.md`
- Modify: `scripts/go2_pointlio/README.md`

**Step 1: Add the explicit authorization gate**

Document that a dynamic run starts only after the user explicitly states that
the remote controller is on and allows the Point-LIO remote-driving test.

The authorization permits:

- starting rosbag;
- starting Point-LIO and RViz2;
- read-only monitoring;
- the user moving the robot with the remote.

It never permits Codex or Jetson software to publish a robot motion command.

**Step 2: Document the future run order**

```text
robot stationary
→ start recorder
→ start Point-LIO
→ wait for initialization and healthy RViz
→ user drives slowly forward for about 5 seconds
→ user stops and confirms stable
→ stop Point-LIO
→ stop rosbag
→ validate/replay data
```

**Step 3: Verify the docs contain no executable motion command**

Add a static test that rejects `sportmoderequest`, `api/sport/request`,
`cmd_vel`, or calls to a Move API anywhere under `scripts/go2_pointlio`.

**Step 4: Run the full test suite**

Run Task 8 Step 8 again.

Expected: PASS.

**Step 5: Commit**

```bash
git add docs/go2/机载L2_Point-LIO技术手册.md \
  scripts/go2_pointlio/README.md \
  scripts/go2_pointlio/tests
git commit -m "docs: prepare safe Point-LIO dynamic validation"
```

Do not perform the dynamic run as part of this implementation plan without a
new, explicit user authorization.
