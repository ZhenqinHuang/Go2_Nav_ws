# MID360S to D435i calibration

Use `direct_visual_lidar_calibration` in an Ubuntu 22.04 ROS2 Humble
environment. Its official Livox workflow accepts ROS2 bags with PointCloud2,
image, and CameraInfo topics.

Prepare a standard calibration bag on Windows:

```powershell
py scripts\prepare_calibration_bag.py SOURCE_BAG CALIBRATION_BAG
```

The output topics are `/livox/points`, `/camera/color/image_raw`, and
`/camera/color/camera_info`. `/livox/points` retains all raw MID360 points and
maps reflectivity to a float32 `intensity` field.

In the calibration toolbox, use manual initial correspondences followed by NID
fine registration. Do not use placeholder values or the optional SuperGlue
workflow for commercial work. Inspect the projected point cloud before accepting
the result.

The toolbox's `T_lidar_camera` maps camera coordinates to LiDAR coordinates,
while FAST-LIVO2 `Rcl/Pcl` maps LiDAR coordinates to camera coordinates. Import
the result through the checked inverse conversion:

```powershell
py scripts\import_calibration_result.py CALIB_JSON BASE_CALIBRATION_YAML OUTPUT_YAML
```

Without `--residual-time-offset-s`, the output intentionally remains
`status: uncalibrated`, so 3D leakage publication stays disabled. Only add that
option after measuring the residual offset from a motion-rich synchronized
capture.

`residual_time_offset_s` is added to an RGB header timestamp before matching it
to LiDAR-derived odometry. A positive value means the camera header time is
earlier than the corresponding LiDAR time. Aligned depth stays on the unshifted
RGB camera clock.
