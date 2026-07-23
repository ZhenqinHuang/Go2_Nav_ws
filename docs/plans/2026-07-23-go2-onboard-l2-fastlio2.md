# Go2 Onboard L2 FAST-LIO2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a reproducible, read-only-first path that feeds the Go2 onboard Unitree 4D LiDAR L2 point cloud and built-in IMU into the existing ROS 2 Foxy FAST-LIO2 installation.

**Architecture:** Keep the MID360 path untouched and add L2-specific assets under `scripts/go2_l2`. A pure-Python validation core makes the input contract testable without ROS, while the live probe imports ROS only at runtime. A foreground launcher sources the existing Unitree, Livox-message, and FAST-LIO2 workspaces and passes the repository-owned L2 YAML to `fast_lio`.

**Tech Stack:** Python 3, `unittest`, PyYAML, Bash, ROS 2 Foxy, CycloneDDS 0.10.2, `sensor_msgs/PointCloud2`, `sensor_msgs/Imu`, Ericsii/FAST_LIO_ROS2.

---

### Task 1: Lock the L2 FAST-LIO2 configuration contract

**Files:**
- Create: `scripts/go2_l2/tests/__init__.py`
- Create: `scripts/go2_l2/tests/test_l2_fastlio_assets.py`
- Create: `scripts/go2_l2/config/go2_l2.yaml`

**Step 1: Write the failing configuration test**

Create a `unittest` that loads `scripts/go2_l2/config/go2_l2.yaml` and asserts:

```python
self.assertEqual(common["lid_topic"], "/utlidar/cloud")
self.assertEqual(common["imu_topic"], "/utlidar/imu")
self.assertFalse(common["time_sync_en"])
self.assertEqual(preprocess["lidar_type"], 2)
self.assertEqual(preprocess["timestamp_unit"], 0)
self.assertEqual(preprocess["scan_line"], 1)
self.assertEqual(mapping["extrinsic_T"], [0.007698, 0.014655, -0.00667])
self.assertEqual(mapping["extrinsic_R"], [1.0, 0.0, 0.0,
                                          0.0, 1.0, 0.0,
                                          0.0, 0.0, 1.0])
```

Also assert that PCD saving is disabled for the first static test.

**Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest -v scripts.go2_l2.tests.test_l2_fastlio_assets
```

Expected: `ERROR` because `go2_l2.yaml` does not exist.

**Step 3: Add the minimal L2 configuration**

Create a complete FAST-LIO2 ROS 2 YAML. Reuse the existing MID360 numerical defaults where sensor-independent, but use:

```yaml
common:
  lid_topic: "/utlidar/cloud"
  imu_topic: "/utlidar/imu"
  time_sync_en: false
  time_offset_lidar_to_imu: 0.0

preprocess:
  lidar_type: 2
  scan_line: 1
  blind: 0.10
  timestamp_unit: 0
  scan_rate: 15

mapping:
  det_range: 30.0
  extrinsic_est_en: false
  extrinsic_T: [0.007698, 0.014655, -0.00667]
```

Set `map_file_path` to `/home/nvidia/Go2_Nav_ws/maps/Go2_L2.pcd` and initially set
`pcd_save_en: false`.

**Step 4: Run the test to verify it passes**

Run:

```powershell
python -m unittest -v scripts.go2_l2.tests.test_l2_fastlio_assets
```

Expected: all configuration tests pass.

**Step 5: Commit**

```powershell
git add scripts/go2_l2
git commit -m "feat: add Go2 L2 FAST-LIO2 configuration"
```

### Task 2: Build the offline-testable L2 input validation core

**Files:**
- Create: `scripts/go2_l2/__init__.py`
- Create: `scripts/go2_l2/l2_input_probe.py`
- Create: `scripts/go2_l2/tests/test_l2_input_probe.py`

**Step 1: Write failing unit tests**

Test pure functions using synthetic inputs:

```python
def test_accepts_required_point_fields(self):
    result = validate_point_fields(
        {"x": 7, "y": 7, "z": 7, "intensity": 7, "ring": 4, "time": 7}
    )
    self.assertEqual(result, [])

def test_reports_missing_time_field(self):
    result = validate_point_fields(
        {"x": 7, "y": 7, "z": 7, "intensity": 7, "ring": 4}
    )
    self.assertIn("time", result[0])

def test_classifies_l2_from_sampling_interval(self):
    model = classify_unitree_lidar(
        raw_sampling_hz=129366.0, effective_points_hz=64000.0
    )
    self.assertEqual(model, "L2")

def test_rejects_l1_for_l2_pipeline(self):
    model = classify_unitree_lidar(
        raw_sampling_hz=43200.0, effective_points_hz=21600.0
    )
    self.assertEqual(model, "L1")
```

Add tests for empty time arrays, non-monotonic time values, and frequency thresholds.

**Step 2: Run the tests to verify they fail**

Run:

```powershell
python -m unittest -v scripts.go2_l2.tests.test_l2_input_probe
```

Expected: import failure because `l2_input_probe.py` does not exist.

**Step 3: Implement minimal pure helpers**

Implement:

```python
REQUIRED_FIELDS = {
    "x": 7, "y": 7, "z": 7, "intensity": 7, "ring": 4, "time": 7
}

def validate_point_fields(fields):
    ...

def analyze_point_times(times):
    ...

def classify_unitree_lidar(raw_sampling_hz, effective_points_hz):
    ...

def evaluate_rates(cloud_hz, imu_hz):
    ...
```

Keep ROS imports out of module import scope so Windows unit tests can import the helpers.

**Step 4: Run tests to verify they pass**

Run:

```powershell
python -m unittest -v scripts.go2_l2.tests.test_l2_input_probe
```

Expected: all helper tests pass.

**Step 5: Commit**

```powershell
git add scripts/go2_l2
git commit -m "test: add Unitree L2 input validation core"
```

### Task 3: Add the read-only live ROS 2 probe

**Files:**
- Modify: `scripts/go2_l2/l2_input_probe.py`
- Modify: `scripts/go2_l2/tests/test_l2_input_probe.py`

**Step 1: Write failing report and safety tests**

Add tests that a synthetic successful sample produces a structured report with:

```python
self.assertEqual(report["detected_model"], "L2")
self.assertTrue(report["ready_for_fastlio2"])
self.assertEqual(report["errors"], [])
```

Add a source-safety assertion that the probe contains neither
`/api/sport/request` nor `unitree_api.msg.Request`.

**Step 2: Run tests to verify they fail**

Run:

```powershell
python -m unittest -v scripts.go2_l2.tests.test_l2_input_probe
```

Expected: failure because report construction and live entry point are absent.

**Step 3: Implement the live probe**

At runtime only, import `rclpy`, `PointCloud2`, `Imu`, and reliable/volatile QoS.
Subscribe to `/utlidar/cloud` and `/utlidar/imu`, collect for a configurable duration,
decode `ring` and `time` through PointCloud2 offsets/datatype metadata, then print JSON.

CLI:

```bash
python3 scripts/go2_l2/l2_input_probe.py \
  --duration 6 \
  --report /tmp/go2_l2_input_report.json
```

Exit `0` only when the input contract is ready for FAST-LIO2; otherwise exit non-zero
and list exact errors.

**Step 4: Run all probe tests**

Run:

```powershell
python -m unittest -v scripts.go2_l2.tests.test_l2_input_probe
```

Expected: all tests pass without ROS installed on Windows.

**Step 5: Commit**

```powershell
git add scripts/go2_l2
git commit -m "feat: add read-only Go2 L2 input probe"
```

### Task 4: Add a safe foreground launcher

**Files:**
- Create: `scripts/go2_l2/run_fastlio2_l2.sh`
- Modify: `scripts/go2_l2/tests/test_l2_fastlio_assets.py`
- Create: `scripts/go2_l2/README.md`

**Step 1: Write failing launcher contract tests**

Assert that the launcher:

- requires `eth0` by default but accepts `UNITREE_INTERFACE`;
- sources `/home/nvidia/unitree_ros2/setup.sh`;
- sources `/home/nvidia/ws_Livox/install/setup.bash`;
- sources `/home/nvidia/ws_fastlio2/install/setup.bash`;
- launches `fast_lio mapping.launch.py`;
- passes `go2_l2.yaml`;
- uses foreground `exec`;
- contains no Sport API topic or movement command;
- supports `--probe-only`.

**Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest -v scripts.go2_l2.tests.test_l2_fastlio_assets
```

Expected: failure because the launcher does not exist.

**Step 3: Implement the launcher and operator README**

The launcher must:

1. use `set -euo pipefail`;
2. verify all setup/config paths;
3. run the live probe before FAST-LIO2 unless `--skip-probe` is explicit;
4. stop on probe failure;
5. start FAST-LIO2 in the foreground so `Ctrl+C` stops it cleanly;
6. never publish a robot-control message.

Document static-only usage and the requirement for renewed permission before motion.

**Step 4: Run launcher and all local tests**

Run:

```powershell
python -m unittest -v `
  scripts.go2_l2.tests.test_l2_fastlio_assets `
  scripts.go2_l2.tests.test_l2_input_probe `
  scripts.go2.tests.test_go2_closed_loop_motion
```

Expected: all tests pass.

**Step 5: Commit**

```powershell
git add scripts/go2_l2
git commit -m "feat: add safe Go2 L2 FAST-LIO2 launcher"
```

### Task 5: Deploy assets to Jetson and verify live L2 input

**Files:**
- Update on Jetson: `/home/nvidia/Go2_Nav_ws`
- Produce on Jetson: `/tmp/go2_l2_input_report.json`

**Step 1: Confirm no conflicting runtime**

Read-only commands:

```bash
pgrep -af 'laser_mapping|fast_lio|go2_closed_loop_motion_test'
ros2 topic info -v /api/sport/request
```

Expected: no FAST-LIO2 or Jetson motion-test process.

**Step 2: Synchronize the branch safely**

Fetch and check out `feature/go2-onboard-l2-fastlio2` in the existing Jetson repository.
Before changing branches, require `git status --short` to be clean or preserve known
installation patches outside the project repository.

**Step 3: Run the repository tests on Jetson**

```bash
cd /home/nvidia/Go2_Nav_ws
python3 -m unittest -v \
  scripts.go2_l2.tests.test_l2_fastlio_assets \
  scripts.go2_l2.tests.test_l2_input_probe \
  scripts.go2.tests.test_go2_closed_loop_motion
```

Expected: all tests pass.

**Step 4: Run the live probe**

```bash
export UNITREE_INTERFACE=eth0
source /home/nvidia/unitree_ros2/setup.sh
python3 /home/nvidia/Go2_Nav_ws/scripts/go2_l2/l2_input_probe.py \
  --duration 6 \
  --report /tmp/go2_l2_input_report.json
```

Expected:

- detected model `L2`;
- required fields present;
- cloud near 15 Hz;
- IMU near 250 Hz;
- no timestamp regression;
- ready for FAST-LIO2.

**Step 5: Record the exact result**

Copy the bounded JSON values into the technical record. Do not commit raw point clouds.

### Task 6: Perform a stationary FAST-LIO2 smoke test

**Files:**
- Produce on Jetson: `/tmp/go2_l2_fastlio2.log`
- Produce on Jetson: `/tmp/go2_l2_static_report.json`

**Step 1: Start FAST-LIO2 with a hard timeout**

Keep the robot stationary and run:

```bash
timeout --signal=INT --kill-after=5 35 \
  bash /home/nvidia/Go2_Nav_ws/scripts/go2_l2/run_fastlio2_l2.sh \
  > /tmp/go2_l2_fastlio2.log 2>&1
```

Expected: the process reaches `Node init finished` and exits due to the test timeout,
not a crash.

**Step 2: Observe outputs from a second read-only shell**

Measure:

```bash
ros2 topic hz /Odometry
ros2 topic hz /cloud_registered
ros2 topic hz /cloud_registered_body
```

Capture bounded odometry samples and compute stationary translation/yaw drift.

**Step 3: Add a regression test before any fix**

If the smoke test exposes a parser, timestamp, QoS, external-parameter, or launch defect,
first reproduce it in the smallest failing local test. Only then modify configuration,
probe, launcher, or the external FAST-LIO2 source.

**Step 4: Re-run the exact failed check**

Expected: the original failure is absent and all local tests remain green.

**Step 5: Commit any verified correction**

Use one focused commit per corrected defect.

### Task 7: Document results and publish the branch

**Files:**
- Create: `docs/go2/机载L2_FAST-LIO2技术手册.md`
- Create: `docs/go2/l2_fastlio2验证记录_2026-07-23.md`
- Modify: `README.md`

**Step 1: Write the technical handoff**

Record:

- hardware identification evidence;
- exact topics, fields, rates, QoS, clock behavior, and external parameters;
- source repositories and pinned commits;
- branch and Jetson paths;
- run, stop, diagnose, and rollback commands;
- static-test outputs;
- unresolved dynamic validation;
- explicit safety boundary forbidding movement without renewed authorization.

**Step 2: Run full verification**

```powershell
python -m unittest -v `
  scripts.go2_l2.tests.test_l2_fastlio_assets `
  scripts.go2_l2.tests.test_l2_input_probe `
  scripts.go2.tests.test_go2_closed_loop_motion
git diff --check
git status --short
```

On Jetson, repeat all repository tests and the live input probe.

**Step 3: Review requirements line by line**

Confirm:

- MID360 assets unchanged;
- no movement publisher added;
- L2 model and point-time contract verified;
- static FAST-LIO2 result backed by fresh logs;
- dynamic validation is clearly marked pending if no motion was authorized.

**Step 4: Commit documentation**

```powershell
git add README.md docs/go2 docs/plans
git commit -m "docs: record onboard L2 FAST-LIO2 validation"
```

**Step 5: Push**

```powershell
git push -u origin feature/go2-onboard-l2-fastlio2
```

Expected: remote branch is created and points to the verified local HEAD.
