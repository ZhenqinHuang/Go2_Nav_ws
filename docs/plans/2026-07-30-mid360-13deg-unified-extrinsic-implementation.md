# MID360 13° Unified Extrinsic Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Use one validated MID360 front-down 13° mount configuration to produce consistent Go2 odometry, base-frame point clouds, new 3D/2D maps, ICP localization, and Nav2 transforms.

**Architecture:** Keep FAST-LIO's LiDAR-to-built-in-IMU calibration unchanged. Add a small shared extrinsics package containing the only mount-angle configuration and pure transform math; use the forward `base_link → body` transform for point coordinates and its inverse for `T_odom_body → T_odom_base`. ICP continues to consume the paired raw FAST-LIO world cloud and raw odometry, while Nav2 consumes corrected `/odom` and `/scan`.

**Tech Stack:** ROS 2 Foxy, Python 3/rclpy, NumPy, nav_msgs, sensor_msgs/PointCloud2, tf2_ros, FAST-LIO2, PCL-based ICP localization, Nav2, pytest, colcon.

---

## Safety and scope

- Do not publish `/cmd_vel`, `/go2/manual_cmd_vel`, navigation goals, or Unitree commands during software deployment.
- Preserve the current working 3D and 2D maps before replacing them.
- Do not change `/home/nvidia/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml` fields `extrinsic_T` or `extrinsic_R`.
- Keep translation, roll, and yaw at their current values; only set mount pitch to `+0.22689280275926285` radians.
- Keep the Web console and the external-to-internal motion gateway out of this change.

### Task 1: Add the shared MID360 mount extrinsics package

**Files:**

- Create: `src/Go2_description/go2_mount_extrinsics/CMakeLists.txt`
- Create: `src/Go2_description/go2_mount_extrinsics/package.xml`
- Create: `src/Go2_description/go2_mount_extrinsics/config/mid360_mount.yaml`
- Create: `src/Go2_description/go2_mount_extrinsics/go2_mount_extrinsics/__init__.py`
- Create: `src/Go2_description/go2_mount_extrinsics/go2_mount_extrinsics/transform_math.py`
- Test: `test/test_mount_extrinsics.py`

**Step 1: Write the failing pure-Python test**

The test must add the new source package directory to `sys.path` and specify:

```python
def test_front_down_mount_and_inverse_cancel():
    mount_q = quaternion_from_rpy(0.0, math.radians(13.0), 0.0)
    inverse_q = quaternion_conjugate(mount_q)
    result = quaternion_multiply(mount_q, inverse_q)
    assert result == pytest.approx((0.0, 0.0, 0.0, 1.0), abs=1e-9)


def test_front_axis_is_down_in_base_frame():
    rotation = rotation_matrix_from_rpy(0.0, math.radians(13.0), 0.0)
    transformed = rotation @ np.array([1.0, 0.0, 0.0])
    assert transformed[0] == pytest.approx(math.cos(math.radians(13.0)))
    assert transformed[2] == pytest.approx(-math.sin(math.radians(13.0)))


def test_mount_config_has_one_13_degree_definition():
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    params = data["/**"]["ros__parameters"]
    assert params["mount_pitch"] == pytest.approx(math.radians(13.0))
    assert params["mount_roll"] == 0.0
    assert params["mount_yaw"] == 0.0
```

**Step 2: Run the test and verify RED**

Run:

```bash
python -m pytest test/test_mount_extrinsics.py -q
```

Expected: FAIL because `go2_mount_extrinsics.transform_math` and the shared YAML do not exist.

**Step 3: Implement the shared math**

`transform_math.py` must provide:

```python
def quaternion_from_rpy(roll, pitch, yaw): ...
def quaternion_multiply(lhs, rhs): ...
def quaternion_conjugate(q): ...
def normalize_quaternion(q): ...
def rotate_vector(q, vector): ...
def rotation_matrix_from_rpy(roll, pitch, yaw): ...
def validate_extrinsics(translation, roll, pitch, yaw): ...
```

All inputs must be finite. `normalize_quaternion` must reject a near-zero norm.

**Step 4: Add the single configuration source**

```yaml
/**:
  ros__parameters:
    mount_translation_x: 0.0
    mount_translation_y: 0.0
    mount_translation_z: 0.0
    mount_roll: 0.0
    mount_pitch: 0.22689280275926285
    mount_yaw: 0.0
```

The parameter direction is the pose of FAST-LIO `body` in `base_link`, namely
`T_base_body`.

**Step 5: Install package and config**

Use `ament_cmake_python` to install the Python package and install `config/` into
`share/go2_mount_extrinsics`.

**Step 6: Run the test and verify GREEN**

Run:

```bash
python -m pytest test/test_mount_extrinsics.py -q
```

Expected: all tests PASS.

**Step 7: Commit**

```bash
git add src/Go2_description/go2_mount_extrinsics test/test_mount_extrinsics.py
git commit -m "feat: add shared MID360 mount extrinsics"
```

### Task 2: Correct FAST-LIO body odometry into Go2 base odometry

**Files:**

- Modify: `src/Go2_localization/odom_tf_bridge/odom_tf_bridge/odom_tf_bridge_node.py`
- Modify: `src/Go2_localization/odom_tf_bridge/config/odom_bridge_params.yaml`
- Modify: `src/Go2_localization/odom_tf_bridge/package.xml`
- Test: `test/test_odom_mount_transform.py`

**Step 1: Write the failing transform contract test**

Test a pure helper callable without ROS:

```python
def test_sensor_pose_is_converted_to_horizontal_base_pose():
    q_odom_body = quaternion_from_rpy(0.0, math.radians(13.0), 0.0)
    q_base_body = quaternion_from_rpy(0.0, math.radians(13.0), 0.0)
    q_odom_base = compose_odom_to_base(q_odom_body, q_base_body)
    assert q_odom_base == pytest.approx((0.0, 0.0, 0.0, 1.0), abs=1e-8)


def test_body_twist_is_rotated_into_base_coordinates():
    q_base_body = quaternion_from_rpy(0.0, math.radians(13.0), 0.0)
    result = body_vector_to_base((1.0, 0.0, 0.0), q_base_body)
    assert result[2] < 0.0
```

`compose_odom_to_base` must compute:

```text
q_odom_base = q_odom_body × conjugate(q_base_body)
```

**Step 2: Run the test and verify RED**

Run:

```bash
python -m pytest test/test_odom_mount_transform.py -q
```

Expected: FAIL because the odometry mount helpers are absent.

**Step 3: Implement the minimal odometry correction**

- Declare and read all shared `mount_*` parameters.
- Build `q_base_body` from the shared forward mount transform.
- Compose the inverse into the output pose.
- Rotate linear and angular twist vectors from `body` coordinates into
  `base_link` coordinates.
- Apply translation using full rigid-transform composition even though current
  translation is zero.
- Publish the corrected pose in both `/odom` and `odom → base_link`.
- Log the configured mount direction and angle once at startup.
- Reject invalid/non-finite extrinsics before subscribing.

**Step 4: Run targeted and regression tests**

Run:

```bash
python -m pytest \
  test/test_mount_extrinsics.py \
  test/test_odom_mount_transform.py \
  test/test_nav2_launch_contract.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add \
  src/Go2_localization/odom_tf_bridge \
  test/test_odom_mount_transform.py
git commit -m "feat: convert FAST-LIO body odometry to base_link"
```

### Task 3: Transform body-frame points before height filtering

**Files:**

- Modify: `src/Go2_perception/pointcloud_to_laserscan/go2_pc2scan/cloud_filter_node.py`
- Modify: `src/Go2_perception/pointcloud_to_laserscan/config/cloud_filter_params.yaml`
- Modify: `src/Go2_perception/pointcloud_to_laserscan/package.xml`
- Test: `test/test_cloud_mount_transform.py`

**Step 1: Write the failing point transform test**

```python
def test_cloud_points_are_rotated_before_height_filtering():
    points_body = np.array([[1.0, 0.0, 0.0]], dtype=np.float64)
    rotation = rotation_matrix_from_rpy(0.0, math.radians(13.0), 0.0)
    points_base = transform_xyz(points_body, rotation, np.zeros(3))
    assert points_base[0, 0] == pytest.approx(math.cos(math.radians(13.0)))
    assert points_base[0, 2] == pytest.approx(-math.sin(math.radians(13.0)))


def test_wrong_input_frame_fails_closed():
    assert validate_input_frame("body", "body") is True
    assert validate_input_frame("base_link", "body") is False
```

**Step 2: Run the test and verify RED**

Run:

```bash
python -m pytest test/test_cloud_mount_transform.py -q
```

Expected: FAIL because `transform_xyz` and frame validation are absent.

**Step 3: Implement the minimal real coordinate transform**

In each callback:

1. Require `msg.header.frame_id == expected_input_frame` (`body` by default).
2. Decode XYZ.
3. Remove non-finite points.
4. Compute:

```python
points_base = points_body @ rotation_base_body.T + translation_base_body
```

5. Publish the finite, transformed cloud on `/cloud_registered_base` with
   `frame_id=base_link`.
6. Apply z/range/voxel filters to `points_base`, not `points_body`.
7. Publish `/cloud_filtered` with `frame_id=base_link`.

Do not merely overwrite `frame_id`.

**Step 4: Run targeted and existing point-cloud tests**

Run:

```bash
python -m pytest \
  test/test_mount_extrinsics.py \
  test/test_cloud_mount_transform.py \
  test/test_repository_contract.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add \
  src/Go2_perception/pointcloud_to_laserscan \
  test/test_cloud_mount_transform.py
git commit -m "feat: transform MID360 body cloud into base_link"
```

### Task 4: Load the same mount YAML in both launch paths

**Files:**

- Modify: `src/Go2_localization/odom_tf_bridge/launch/odom_bridge.launch.py`
- Modify: `src/Go2_perception/pointcloud_to_laserscan/launch/pc2scan.launch.py`
- Modify: `src/Go2_localization/odom_tf_bridge/package.xml`
- Modify: `src/Go2_perception/pointcloud_to_laserscan/package.xml`
- Test: `test/test_mount_launch_contract.py`

**Step 1: Write a failing launch-source contract**

The test must require:

- both launch files resolve `go2_mount_extrinsics`;
- both load `config/mid360_mount.yaml`;
- neither launch file hard-codes `0.2268928` or `13.0`;
- `pc2scan.launch.py` exposes `/cloud_registered_base`;
- package manifests declare `go2_mount_extrinsics`.

**Step 2: Run test and verify RED**

Run:

```bash
python -m pytest test/test_mount_launch_contract.py -q
```

Expected: FAIL because the shared config is not loaded.

**Step 3: Update launch files**

Use:

```python
mount_config = os.path.join(
    get_package_share_directory("go2_mount_extrinsics"),
    "config",
    "mid360_mount.yaml",
)
```

Pass `mount_config` to both nodes before package-specific parameter files so
specific topic/QoS values remain independently configurable.

**Step 4: Run tests**

```bash
python -m pytest \
  test/test_mount_launch_contract.py \
  test/test_nav2_launch_contract.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add \
  src/Go2_localization/odom_tf_bridge \
  src/Go2_perception/pointcloud_to_laserscan \
  test/test_mount_launch_contract.py
git commit -m "build: share MID360 mount config across launch paths"
```

### Task 5: Add startup validation and map/extrinsic version coupling

**Files:**

- Modify: `src/Go2_bringup/check_nav2_ready.sh`
- Modify: `src/Go2_bringup/go2_nav_start.sh`
- Create: `maps/MID360.extrinsics.yaml`
- Test: `test/test_mount_bringup_contract.py`

**Step 1: Write the failing bringup contract**

Require checks for:

- `/cloud_registered_base`;
- `/scan` frame `base_link`;
- only one parent of `base_link`;
- the shared mount config hash matching `maps/MID360.extrinsics.yaml`;
- finite `map → odom → base_link`;
- no startup if map metadata and active extrinsics mismatch.

**Step 2: Run test and verify RED**

```bash
python -m pytest test/test_mount_bringup_contract.py -q
```

Expected: FAIL because the checks and metadata are absent.

**Step 3: Implement fail-closed startup checks**

At map creation time, write:

```yaml
mount_config_sha256: "<sha256>"
mount_pitch_rad: 0.22689280275926285
direction: "front_down"
pcd: "MID360.pcd"
occupancy_map: "MID360_map.yaml"
```

At navigation startup, compare the active shared YAML hash with the map
metadata. Abort before Nav2 if they differ.

**Step 4: Run tests**

```bash
python -m pytest \
  test/test_mount_bringup_contract.py \
  test/test_nav2_launch_contract.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add \
  src/Go2_bringup \
  maps/MID360.extrinsics.yaml \
  test/test_mount_bringup_contract.py
git commit -m "feat: validate map and mount extrinsic compatibility"
```

### Task 6: Make map replacement recoverable

**Files:**

- Modify: `src/Go2_bringup/build_map.sh`
- Create: `src/Go2_bringup/backup_maps.sh`
- Test: `test/test_map_backup_contract.py`

**Step 1: Write the failing backup contract**

Require the scripts to:

- resolve absolute paths under `${GO2_NAV_WS}/maps`;
- create `${GO2_NAV_WS}/maps/backups/<timestamp>/`;
- copy existing `MID360.pcd`, `.pgm`, `.yaml`, and `.extrinsics.yaml`;
- refuse an empty PCD;
- use a temporary output prefix and atomically replace the active map only
  after PCD-to-map succeeds.

**Step 2: Run test and verify RED**

```bash
python -m pytest test/test_map_backup_contract.py -q
```

Expected: FAIL because safe backup/atomic replacement is absent.

**Step 3: Implement scripts**

Do not delete the active map. Backup first, generate temporary outputs, verify
all expected files, then use same-filesystem `mv` for replacement.

**Step 4: Run tests**

```bash
python -m pytest test/test_map_backup_contract.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add \
  src/Go2_bringup/build_map.sh \
  src/Go2_bringup/backup_maps.sh \
  test/test_map_backup_contract.py
git commit -m "feat: add recoverable MID360 map replacement"
```

### Task 7: Build and run all local static tests

**Files:** No production changes unless verification finds a defect.

**Step 1: Run Python tests**

```bash
python -m pytest test -q
```

Expected: all tests PASS.

**Step 2: Run syntax checks**

```bash
python -m py_compile \
  src/Go2_description/go2_mount_extrinsics/go2_mount_extrinsics/*.py \
  src/Go2_localization/odom_tf_bridge/odom_tf_bridge/*.py \
  src/Go2_perception/pointcloud_to_laserscan/go2_pc2scan/*.py
```

Expected: exit 0.

**Step 3: Run diff hygiene**

```bash
git diff --check
```

Expected: no whitespace errors.

**Step 4: Build on Jetson staging source**

```bash
cd /home/nvidia/Go2_Nav_ws
source /opt/ros/foxy/setup.bash
colcon build --symlink-install --packages-select \
  go2_mount_extrinsics odom_tf_bridge go2_pc2scan go2_bringup
```

Expected: four packages finish with exit 0.

### Task 8: Deploy without moving the robot and verify static consistency

**Files:** Deployment only.

**Step 1: Record the current runtime**

Capture:

```bash
ros2 topic echo /Odometry
ros2 topic echo /odom
ros2 run tf2_ros tf2_echo odom base_link
ros2 topic echo /cloud_registered_body
ros2 topic echo /scan
```

Do not send goals.

**Step 2: Stop only localization/navigation perception processes**

Stop and verify termination of:

- `odom_tf_bridge`;
- `fast_lio_localization_ros2`;
- `go2_pc2scan`;
- Nav2 and Nav2 RViz.

Keep the Web service and motion gateway unchanged.

**Step 3: Start the corrected static chain**

Start FAST-LIO, corrected odometry bridge, corrected point-cloud conversion,
ICP localization, then Nav2 in that order.

**Step 4: Verify static invariants**

Expected:

- one `odom_tf_bridge_node`;
- one cloud filter;
- `/cloud_registered_base` and `/scan` are live;
- `/scan.header.frame_id == base_link`;
- `base_link` has one TF parent;
- no mount/config mismatch error;
- no commands are published.

**Step 5: Visual inspection checkpoint**

In RViz/Web confirm robot footprint, scan, and map overlay. If pitch direction
is opposite, stop and inspect the sign convention; do not stack another
compensation elsewhere.

### Task 9: Rebuild 3D and 2D maps

**Files:** Runtime map artifacts under `/home/nvidia/Go2_Nav_ws/maps`.

**Step 1: Back up the active maps**

```bash
bash /home/nvidia/Go2_Nav_ws/src/Go2_bringup/backup_maps.sh
```

Expected: timestamped backup directory containing all current map artifacts.

**Step 2: Start mapping only**

Start Livox and FAST-LIO with RViz. Do not start ICP or Nav2 while building the
new map.

**Step 3: Validate the stationary cloud**

Confirm floors are horizontal, walls vertical, and the corrected `base_link`
axes agree with the robot front.

**Step 4: Ask the operator before motion**

Only after the user confirms the path is safe, traverse the mapping area.

**Step 5: Save the PCD**

```bash
ros2 service call /map_save std_srvs/srv/Trigger '{}'
```

Expected: `success=True`.

**Step 6: Convert and atomically activate the 2D map**

```bash
GO2_NAV_WS=/home/nvidia/Go2_Nav_ws \
PCD_FILE=/home/nvidia/Go2_Nav_ws/maps/MID360.pcd \
OUTPUT_PATH=/home/nvidia/Go2_Nav_ws/maps/MID360_map \
bash /home/nvidia/Go2_Nav_ws/src/Go2_bringup/build_map.sh
```

Expected: non-empty `.pcd`, `.pgm`, `.yaml`, and matching extrinsics metadata.

### Task 10: Validate ICP and Nav2 on the new map

**Files:** No changes unless evidence exposes a separate defect.

**Step 1: Start localization and navigation**

Use the new `MID360.pcd` for ICP and `MID360_map.yaml` for Nav2.

**Step 2: Verify localization**

Collect at least three stationary ICP samples:

- MSE below `localization_th`;
- no repeated `max_delta_xy` or yaw-gate rejection;
- `map → odom → base_link` remains finite and continuous.

**Step 3: Verify visual alignment**

Check Web and RViz:

- robot icon at the physical location;
- scan walls overlap map walls;
- footprint orientation matches robot front.

**Step 4: Run motion tests only after explicit notice**

Test order:

1. short manual translation already proven by the gateway;
2. one nearby Nav2 goal;
3. one farther single goal;
4. `/FollowWaypoints` multi-point navigation.

Announce every real movement test before sending it.

**Step 5: Final verification**

Run:

```bash
bash /home/nvidia/Go2_Nav_ws/src/Go2_bringup/check_nav2_ready.sh
```

Expected: no failed TF, topic, freshness, map/extrinsic, or lifecycle checks.

