# Windows Bag Viewer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a minimal Windows Python player for point cloud, trajectory, RGB, and depth data in the synchronized ROS2 bag.

**Architecture:** Stream selected bag messages in timestamp order with `rosbags`; decode data with NumPy; render one 3D and two image views through Matplotlib embedded in Tkinter. Keep decoding functions separate so they can be tested without opening a GUI.

**Tech Stack:** Python 3.12, rosbags, NumPy, Matplotlib, Tkinter, unittest

---

### Task 1: Message decoders

**Files:**
- Create: `playback/test_windows_bag_viewer.py`
- Create: `playback/windows_bag_viewer.py`

1. Write failing tests for PointCloud2 XYZ extraction, RGB/depth decoding, and Path XYZ extraction.
2. Run `python -m unittest playback/test_windows_bag_viewer.py -v`; expect import failure.
3. Implement the minimum NumPy decoding functions with input validation.
4. Re-run the test; expect all decoder tests to pass.

### Task 2: Bag validation and timed reader

**Files:**
- Modify: `playback/test_windows_bag_viewer.py`
- Modify: `playback/windows_bag_viewer.py`

1. Write failing tests for required-topic validation.
2. Implement required-topic validation and a sequential four-topic reader.
3. Run the unit tests.
4. Run `python playback/windows_bag_viewer.py <bag> --check`; expect four topic counts and a 23.9-second duration.

### Task 3: Minimal GUI and launcher

**Files:**
- Modify: `playback/windows_bag_viewer.py`
- Create: `playback/run_windows_viewer.bat`
- Modify: `playback/README.md`

1. Add the Tkinter/Matplotlib player with a 3D plot, RGB view, depth view, play/pause button, and elapsed time.
2. Add the launcher pointing at the bag directory beside the script.
3. Run all unit tests and `--check` mode.
4. Copy the files to the extracted local session and launch the viewer for a manual smoke test.
