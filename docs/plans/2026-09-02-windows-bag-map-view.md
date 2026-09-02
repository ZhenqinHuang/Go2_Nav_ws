# Windows Bag Map View Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Render a complete dim Fast-LIO map, a highlighted current scan, and a green cumulative trajectory without 3D axes.

**Architecture:** Preload and combine registered scans in a first read-only bag pass, then retain the existing timestamp-driven playback pass. Render the base map once and only update the current-scan and path artists.

**Tech Stack:** Python, rosbags, NumPy, Matplotlib, Tkinter, unittest

---

### Task 1: Base-map accumulation

**Files:**
- Modify: `playback/test_windows_bag_viewer.py`
- Modify: `playback/windows_bag_viewer.py`

1. Write a failing test that combines multiple point-cloud arrays into one map.
2. Run the test and verify the expected import failure.
3. Implement the minimum combination helper and read-only bag preloading pass.
4. Run all unit tests.

### Task 2: Map-oriented rendering

**Files:**
- Modify: `playback/windows_bag_viewer.py`

1. Render the complete map once in dim gray and fix the scene limits from it.
2. Hide the 3D axes, highlight the current scan in orange-yellow, and draw the path in green.
3. Keep RGB/depth rendering unchanged.
4. Run tests, `--check`, and a full GUI smoke test.

### Task 3: Deliver updated viewer

**Files:**
- Update local artifact: `artifacts/leakage_session_20260902/windows_bag_viewer.py`
- Update local archive: `artifacts/leakage_session_20260902.tar.gz`

1. Copy the verified viewer into the extracted session.
2. Rebuild the archive while retaining the previous archive as backup.
3. Verify archive contents, message count, and SHA-256.
