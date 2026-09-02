# Windows Bag Viewer Design

## Goal

Display the synchronized Fast-LIO point cloud/path and D435i RGB/depth streams
on Windows without requiring a ROS2 installation.

## Design

`windows_bag_viewer.py` reads the ROS2 SQLite bag sequentially with `rosbags`.
It deserializes only four topics and advances them using bag timestamps. A
Tkinter window embeds one Matplotlib 3D view for the point cloud and trajectory,
plus RGB and depth image views. Playback is sequential with play/pause and an
elapsed-time label; seeking, editing, and export are intentionally omitted.

Pure NumPy decoding functions handle PointCloud2, Image, and Path messages and
are covered by standard-library unit tests. A `--check` mode validates the bag
without opening a window. `run_windows_viewer.bat` starts the viewer against the
bag in the same directory.

## Error handling

The viewer rejects missing bag directories, missing required topics, unknown
image encodings, malformed point-cloud buffers, and missing Python packages with
clear messages. It never modifies the bag.

