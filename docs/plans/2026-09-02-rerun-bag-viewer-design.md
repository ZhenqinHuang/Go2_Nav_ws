# Rerun ROS2 Bag Viewer Design

## Goal

Replace the custom Matplotlib rendering path with a small Rerun-based Windows
viewer while keeping the existing script as a fallback. The viewer must play
the recorded Fast-LIO map, current scan, cumulative trajectory, RGB image, and
depth image on one synchronized timeline.

## Chosen approach

Use the open-source `rerun-sdk`. Rerun already provides GPU 3D rendering,
image panels, camera controls, entity visibility, and a playback timeline.
Open3D was rejected because it would require custom playback, synchronization,
layout, and control code. The current Matplotlib/Tkinter viewer remains usable
when installing Rerun is not possible.

## Interface

One application window contains:

- a **Complete map** 3D tab;
- an **Incremental map** 3D tab;
- synchronized RGB and depth panels;
- Rerun's native timeline and playback controls.

Both 3D tabs use a black background with grid, origin axes, and bounding-box
decorations hidden. The map is low brightness, the current scan is bright
magenta, and the cumulative Fast-LIO path is green.

## Data flow

The existing `rosbags` reader remains the single bag decoder.

1. Read `/record/cloud_registered`, `/fastlio_path`, RGB, and depth topics in
   bag timestamp order.
2. Downsample all registered scans into one static complete-map entity.
3. Log each scan once under a persistent per-frame incremental-map entity so
   earlier scans remain visible as the timeline advances.
4. Log the same scan to a time-varying current-scan entity for highlighting.
5. Log each cumulative path update as a green 3D line strip.
6. Log RGB and depth frames on the same bag-time timeline.
7. Apply a Rerun blueprint containing the two selectable 3D tabs and the two
   image views.

## Error handling

Fail with a clear message when the bag is missing, required topics are absent,
or `rerun-sdk` is not installed. Preserve the bag and existing viewer. Never
rewrite recorded data.

## Verification

- Unit-test mode parsing and entity preparation with small synthetic arrays.
- Run the existing viewer tests to prevent fallback regressions.
- Convert and open the recorded session, then verify both tabs, timeline
  playback, current-scan highlighting, cumulative path, RGB, and depth.

