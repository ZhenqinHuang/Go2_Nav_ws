# 地图工作流

## 一套地图，两个用途

同一次 FAST-LIO2 建图必须生成：

```text
maps/MID360.pcd       # 三维 ICP 定位
maps/MID360_map.pgm   # Nav2 栅格图像
maps/MID360_map.yaml  # Nav2 地图元数据
maps/map_manifest.yaml
```

不能将旧 PCD 与新 PGM/YAML 混用，否则 `map` 原点和机器人定位可能不一致。

## 建图

```bash
ros2 launch livox_ros_driver2 msg_MID360s_launch.py
ros2 launch fast_lio mapping.launch.py \
  config_path:=/home/nvidia/ws_fastlio2/src/FAST_LIO_ROS2/config \
  config_file:=mid360.yaml rviz:=true
```

建图结束后，把新 PCD 和由该 PCD 生成的 PGM/YAML 写入 staging。不要直接覆盖当前 active 文件。

## 激活规则

地图工具必须依次完成：

1. 验证 PCD/PGM/YAML 都存在且非空；
2. 验证 YAML 的 `image` 指向同一 bundle 的 PGM；
3. 计算 SHA-256 并写 Manifest；
4. 将当前 active bundle 移入 `maps/archive/<timestamp>/`；
5. 原子提升 staging bundle；
6. 再次校验 active bundle。

启动 ICP 和 Nav2 时只接受校验通过的 active bundle。历史地图默认不进入源码版本库。

## 导航前检查

```bash
ros2 topic hz /odom
ros2 topic hz /scan
ros2 topic hz /map_to_odom
ros2 run tf2_ros tf2_echo map base_link
```

除 topic 存在外，还必须检查消息新鲜度、TF 可查询性和定位是否剧烈跳变。
