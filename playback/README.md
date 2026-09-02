# Leakage synchronized bag playback

This session contains synchronized Fast-LIO point cloud, odometry/path, RGB,
and depth data. It was recorded on ROS2 Foxy.

## Windows viewer (no ROS2 required)

Install the Python dependencies once:

```powershell
python -m pip install --user rosbags numpy matplotlib zstandard ruamel.yaml lz4
```

Then double-click `run_windows_viewer.bat`. The window shows the Fast-LIO point
cloud and trajectory on the left, and synchronized RGB/depth images on the
right. Use the button at the bottom to pause or resume playback.

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
