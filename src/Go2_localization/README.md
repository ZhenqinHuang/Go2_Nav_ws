# Go2 localization

定位层把 FAST-LIO2 输出适配为 Nav2 标准坐标系，并使用三维地图修正全局位姿。

```text
/Odometry (camera_init -> body)
  -> odom_tf_bridge
  -> /odom (odom -> base_link)

/cloud_registered + /home/nvidia/Go2_Nav_ws/maps/MID360.pcd
  -> fast_lio_localization_ros2
  -> /map_to_odom -> map -> odom
```

完整 TF 为 `map -> odom -> base_link`。`/cloud_registered_body` 不用于 ICP；它由感知层转换为
`/scan`。定位包不再携带地图副本，唯一默认 PCD 是仓库根目录 `maps/MID360.pcd`。

## 启动

推荐使用统一入口：

```bash
bash scripts/start_navigation.sh
```

单独调试：

```bash
ros2 launch odom_tf_bridge odom_bridge.launch.py base_frame:=base_link
ros2 launch fast_lio_localization_ros2 localize_go2.launch.py \
  map:=/home/nvidia/Go2_Nav_ws/maps/MID360.pcd rviz:=false
```

## 通过条件

```bash
ros2 topic hz /odom
ros2 topic hz /map_to_odom
ros2 topic hz /localization
ros2 run tf2_ros tf2_echo map base_link
```

ICP 地图和 Nav2 的 PGM/YAML 必须由同一次建图产生，并通过 `maps/map_manifest.yaml` 校验。
地图切换使用 `python3 scripts/map_bundle.py promote ...`，不要直接覆盖单个文件。
