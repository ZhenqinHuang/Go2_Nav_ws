# Leakage synchronized bag playback

This session contains synchronized Fast-LIO point cloud, odometry/path, RGB,
and depth data. It was recorded on ROS2 Foxy.

## Windows viewer (no ROS2 required)

Install the Python dependencies once:

```powershell
python -m pip install --user rosbags numpy matplotlib rerun-sdk==0.37.0 zstandard ruamel.yaml lz4
```

Then double-click `run_windows_viewer.bat`. The Rerun window provides two tabs:

- `Complete map`: the final map is visible immediately at low brightness.
- `Incremental map`: registered scans accumulate as the timeline advances.

Both tabs show the current scan in magenta and the cumulative Fast-LIO path in
green. RGB and depth images are synchronized on the right; YOLO leakage masks
are overlaid in red when recorded. Calibrated `/leakage/points` accumulate as
bright red points in both 3D map tabs. Aligned depth is preferred automatically,
with raw depth retained as a fallback for older bags. Use Rerun's bottom
timeline to play, pause, scrub, or change playback speed.

The launcher opens `leakage_session.rerun.rrd` when that cache is present;
otherwise it builds the same view directly from the ROS2 bag. To use the old
Matplotlib/Tkinter viewer instead, run:

```powershell
python windows_bag_viewer.py . --legacy
```

## ROS2/RViz playback

Use Ubuntu 20.04 with ROS2 Foxy Desktop installed:

```bash
tar -xzf leakage_session_20260902.tar.gz
cd leakage_session_20260902
chmod +x play.sh
./play.sh
```

RViz uses `camera_init` as the fixed frame and displays:

- `/record/cloud_registered`
- `/fastlio_path`
- `/camera/color/image_raw`
- `/camera/depth/image_rect_raw`

The raw bag can also be played with:

```bash
ros2 bag play .
```
