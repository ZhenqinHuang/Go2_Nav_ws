# Rerun Bag Viewer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a polished Rerun Windows viewer with switchable complete-map and incremental-map tabs while preserving the existing Matplotlib fallback.

**Architecture:** Keep all ROS2 decoding in `windows_bag_viewer.py`. Add small data-preparation helpers and a Rerun playback path that logs bag-timestamped entities, then supplies a fixed Blueprint with two 3D tabs and RGB/depth views. The existing Tkinter path remains behind `--legacy`.

**Tech Stack:** Python 3.12, rosbags, NumPy, rerun-sdk 0.37.0, unittest

---

### Task 1: Test deterministic display helpers

**Files:**
- Modify: `playback/test_windows_bag_viewer.py`
- Modify: `playback/windows_bag_viewer.py`

**Step 1: Write the failing tests**

Add tests proving that height colors are `uint8`, bounded, deterministic, and
that incremental frame paths are zero-padded and unique.

```python
colors = height_colors(np.asarray([[0, 0, 0], [0, 0, 10]]), brightness=0.5)
self.assertEqual(colors.dtype, np.uint8)
self.assertEqual(colors.shape, (2, 3))
self.assertEqual(incremental_entity_path(12), "/incremental/map/frame_000012")
```

**Step 2: Run the tests to verify they fail**

Run: `py -m unittest playback/test_windows_bag_viewer.py -v`

Expected: import failure for the new helpers.

**Step 3: Implement the minimum helpers**

Use NumPy interpolation for a dark green-to-yellow map palette and a formatted
entity path. Empty clouds must return an empty `(0, 3)` `uint8` array.

**Step 4: Run the tests to verify they pass**

Run: `py -m unittest playback/test_windows_bag_viewer.py -v`

Expected: all tests pass.

**Step 5: Commit**

```powershell
git add playback/windows_bag_viewer.py playback/test_windows_bag_viewer.py
git commit -m "test: cover Rerun map display helpers"
```

### Task 2: Add Rerun playback and two map tabs

**Files:**
- Modify: `playback/windows_bag_viewer.py`

**Step 1: Install the pinned runtime**

Run: `py -m pip install --user rerun-sdk==0.37.0`

Expected: `import rerun` succeeds.

**Step 2: Add the Rerun Blueprint**

Create one `rrb.Tabs` container with:

- `Complete map`: `/complete/**`, `/current/**`, and `/trajectory/**`;
- `Incremental map`: `/incremental/**`, `/current/**`, and `/trajectory/**`.

Put the tabs beside two `Spatial2DView` image panels. Set 3D backgrounds to
black, `LineGrid3D(visible=False)`, and `SpatialInformation(show_axes=False,
show_bounding_box=False)`.

**Step 3: Log the synchronized bag**

Implement `play_bag_rerun(directory)`:

1. Validate the directory and required topics.
2. Load and log the combined complete map timelessly at low brightness.
3. Walk selected messages in bag timestamp order and set timeline `bag_time`.
4. Log each registered scan to a unique persistent incremental entity and the
   shared bright current-scan entity.
5. Log cumulative path as `LineStrips3D(colors=[0, 255, 102], radii=0.025)`.
6. Log RGB with `Image` and depth with `DepthImage(meter=1000)`.
7. Spawn the viewer and keep the process alive until the viewer closes.

**Step 4: Preserve the fallback CLI**

Make Rerun the default. Add `--legacy` to call the current Tkinter
`play_bag`; keep `--check` unchanged. If Rerun is missing, print the exact
installation command without altering the bag.

**Step 5: Run automated checks**

Run:

```powershell
py -m unittest playback/test_windows_bag_viewer.py -v
py playback/windows_bag_viewer.py <bag-directory> --check
```

Expected: all unit tests pass and four topic counts are printed.

**Step 6: Commit**

```powershell
git add playback/windows_bag_viewer.py
git commit -m "feat: add Rerun dual-mode bag playback"
```

### Task 3: Update the Windows handoff

**Files:**
- Modify: `playback/README.md`
- Modify: `playback/run_windows_viewer.bat`
- Update local artifact: `D:/Github/Go2_Nav_ws/artifacts/leakage_session_20260902/windows_bag_viewer.py`
- Update local artifact: `D:/Github/Go2_Nav_ws/artifacts/leakage_session_20260902/run_windows_viewer.bat`
- Update local artifact: `D:/Github/Go2_Nav_ws/artifacts/leakage_session_20260902/README.md`

**Step 1: Update install and launch instructions**

Document `rerun-sdk==0.37.0`, the two tabs, native timeline controls, and
`--legacy`. Keep the batch file a one-command launcher against its own folder.

**Step 2: Copy only the three updated handoff files**

Do not modify `metadata.yaml`, SQLite bag files, or recorded media.

**Step 3: Rebuild the archive safely**

Create a new temporary archive, validate it, then replace the old archive.
Print its SHA256.

**Step 4: Commit repository documentation**

```powershell
git add playback/README.md playback/run_windows_viewer.bat
git commit -m "docs: add Rerun Windows playback instructions"
```

### Task 4: Verify the recorded session

**Files:**
- No source changes expected

**Step 1: Run all unit tests**

Run: `py -m unittest discover -s playback -p "test_*.py" -v`

Expected: all tests pass.

**Step 2: Generate a Rerun recording without opening a window**

Add or use a CLI `--save <file.rrd>` path so the same logging code can be
verified headlessly. Run it against the recorded session and require a
non-empty `.rrd` file.

**Step 3: Open the verified recording**

Launch the `.rrd` in Rerun. Confirm both map tabs, current scan, green path,
RGB/depth panels, and timeline playback are present. The viewer is closed
manually after visual verification.

**Step 4: Record the decision in Memorix**

Store the selected Rerun architecture, pinned version, verification result,
and relevant commits under stable topic key `architecture/windows-bag-viewer`.

