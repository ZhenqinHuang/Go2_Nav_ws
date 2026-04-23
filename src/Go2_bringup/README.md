# Go2 Bringup

本目录用于放置 Go2 导航链路的人工启动脚本。当前项目统一以 shell 脚本为主，不再使用 `ros2 launch go2_bringup ...` 作为总入口。

目标运行环境：

- Ubuntu 20.04
- ROS 2 Foxy
- Unitree Go2
- Livox MID360
- FAST-LIO2

## 脚本说明

### `go2_nav_start.sh`

用于启动 Nav2 前置数据流，按顺序拉起并检查以下链路：

1. Livox MID360 驱动
2. FAST-LIO2 里程计/点云输出
3. `/Odometry` 到 `/odom` 和 `odom -> base_link` 的转换
4. `/cloud_registered_body` 到 `/scan` 的转换
5. 最后检查关键节点、关键话题和话题频率

默认启动命令：

```bash
bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh
```

如果在 Go2 实机上使用 `/home/unitree` 路径，可以显式覆盖工作空间路径：

```bash
LIVOX_WS=/home/unitree/ws_Livox \
FASTLIO_WS=/home/unitree/ws_fastlio2 \
GO2_NAV_WS=/home/unitree/Go2_Nav_ws \
FASTLIO_CONFIG=/home/unitree/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml \
bash /home/unitree/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh
```

主要输出：

- `/livox/lidar`
- `/livox/imu`
- `/Odometry`
- `/cloud_registered_body`
- `/odom`
- `odom -> base_link`
- `/cloud_filtered`
- `/scan`

日志默认保存到：

```bash
/tmp/go2_nav_bringup/
```

### `time_sync_start.sh`

用于启动 Go2 主机与 MID360 的时间同步辅助流程：

1. 使用 NTP 校准本机系统时间
2. 启动 `ptp4l`，让本机作为 PTP Master
3. 通过 PTP 向 MID360 提供时间同步
4. 持续打印主机时间与 NTP 时间的误差

该脚本需要 root 权限：

```bash
sudo bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/time_sync_start.sh
```

时间同步配置主要来自：

```bash
/home/wangzhenjie/Go2_Nav_ws/src/Go2_time_sync/config/ptp_sync.yaml
```

## 推荐启动顺序

实机运行时建议先启动时间同步，再启动导航前置链路：

```bash
sudo bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/time_sync_start.sh
```

另开一个终端：

```bash
bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh
```

## 当前约定

- Livox 驱动工作空间默认在 `~/ws_Livox`
- FAST-LIO2 工作空间默认在 `~/ws_fastlio2`
- 本项目工作空间默认在 `~/Go2_Nav_ws`
- FAST-LIO2 配置文件默认使用 `~/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml`
- 若实机路径不同，优先通过环境变量覆盖，不建议在脚本中写死机器专属路径
