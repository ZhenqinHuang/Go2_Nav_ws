# Leakage Recording Chain Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the existing rosbag2 script capture replayable registered point clouds, trajectory, RGB, and depth reliably.

**Architecture:** Reuse `trajectory_recorder` for portable PointCloud2/Odometry topics and retain raw Livox topics. Extend the existing preflight by one PointCloud2 subscription and pass the existing QoS file to rosbag2.

**Tech Stack:** ROS 2 Foxy, rosbag2, Python/rclpy, Bash, pytest

---

### Task 1: Lock recording requirements with tests

**Files:**
- Create: `src/leakage_bringup/test/test_recording_config.py`

1. Assert `config/record_topics.txt` contains `/record/cloud_registered` and `/record/odometry`.
2. Assert `scripts/record_leakage_session.sh` passes `--qos-profile-overrides-path`.
3. Assert `wait_for_topics.py` subscribes to `/record/cloud_registered` and requires `cloud`.
4. Run `pytest src/leakage_bringup/test/test_recording_config.py -q`; expect failures for all missing behavior.

### Task 2: Implement the minimum recording fix

**Files:**
- Modify: `config/record_topics.txt`
- Modify: `scripts/record_leakage_session.sh`
- Modify: `src/leakage_bringup/leakage_bringup/wait_for_topics.py`

1. Add both relay topics to the topic list.
2. Pass the existing QoS file to `ros2 bag record`.
3. Add one PointCloud2 preflight subscription and the `cloud` state.
4. Run the focused test; expect PASS.

### Task 3: Verify and deploy

**Files:**
- Deploy only the changed runtime files to `/home/nvidia/leakage_location_ws`.

1. Run the complete local test suite; expect PASS.
2. Copy changed runtime files to Jetson without replacing unrelated files.
3. Restart `trajectory_recorder` to clear the old path.
4. Run preflight and confirm path, cloud, RGB, and depth messages are received.
