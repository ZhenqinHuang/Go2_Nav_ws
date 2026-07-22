# MID360 Jetson 集成设计

**状态：** 已确认

**日期：** 2026-07-23

**目标平台：** Jetson Orin NX 16GB，Ubuntu 20.04，ROS 2 Foxy

## 1. 背景与目标

`Go2_Nav_ws` 已经实现 Nav2、点云转 LaserScan、FAST-LIO 地图重定位和一键启动框架，但 Jetson 上尚未安装 MID360 的底层 SDK、ROS 2 驱动和 FAST-LIO2 建图节点。

本次工作要在雷达尚未到货的情况下完成：

1. 安装并固定 Livox SDK2、Livox ROS Driver 2 和 ROS 2 版 FAST-LIO2；
2. 准备 MID360 直连 Jetson 的独立网口；
3. 让现有 `Go2_Nav_ws` 能找到约定的两个外部工作空间；
4. 完成无硬件条件下可执行的编译、环境和 launch 静态验证；
5. 保存完整技术手册、源码版本、问题记录、回滚方法和到货后的验收步骤。

不在本阶段宣称真实点云、IMU 或里程计已经可用；这些必须等 MID360 到货后通过实机数据验证。

## 2. 已确认的架构决策

### 2.1 物理拓扑

MID360 数据网线直接连接 Jetson 的 `eth0`。Jetson 的 `wlan0` 继续承载 SSH、互联网和现有机器人通信。

```text
MID360
  │  Ethernet / UDP
  ▼
Jetson eth0: 192.168.1.5/24
  ├─ livox_ros_driver2  → /livox/lidar, /livox/imu
  ├─ FAST_LIO_ROS2     → /Odometry, /cloud_registered
  └─ Go2_Nav_ws        → odom、定位、LaserScan、Nav2

Jetson wlan0: 现有 192.168.0.x 网络、SSH 和互联网
```

不让宇树机载电脑充当 MID360 到 Jetson 的数据转发节点，以避免额外的路由、UDP 转发、带宽和丢包故障点。如果将来多台计算机必须同时访问雷达，使用独立以太网交换机。

### 2.2 FAST-LIO 代码来源

不直接安装 ROS 1 的 `hku-mars/FAST_LIO`。它保留为算法上游参考。

运行版本采用 `Ericsii/FAST_LIO_ROS2` 的 `ros2` 分支，因为当前系统是 ROS 2 Foxy，现有 Go2 启动链路也使用 ROS 2 话题和 launch 文件。

### 2.3 工作空间边界

保持现有工程约定，不把第三方大型仓库复制进 `Go2_Nav_ws`：

| 路径 | 内容 |
|---|---|
| `/home/nvidia/Go2_Nav_ws` | Go2 导航、定位、感知与启动脚本 |
| `/home/nvidia/ws_Livox` | `livox_ros_driver2` ROS 2 工作空间 |
| `/home/nvidia/ws_fastlio2` | `FAST_LIO_ROS2` ROS 2 工作空间 |
| `/usr/local` | Livox-SDK2 头文件和库 |

这样与 `go2_nav_start.sh` 的默认值一致，也便于独立升级和回滚第三方组件。

## 3. 固定源码版本

安装与手册必须记录以下版本，不使用不可复现的浮动 `master`：

| 组件 | 来源 | 固定版本 |
|---|---|---|
| Livox-SDK2 | <https://github.com/Livox-SDK/Livox-SDK2> | tag `v1.3.1`, commit `f5d9375f84efe2b15bc0a052d3e18482ed13adf4` |
| livox_ros_driver2 | <https://github.com/Livox-SDK/livox_ros_driver2> | commit `13eb05e4e6dd7a765b934d0c5fd6236676a57b49` |
| FAST_LIO_ROS2 | <https://github.com/Ericsii/FAST_LIO_ROS2> | branch `ros2`, commit `2fffc570a25d0df172720bac034fbdb6a13d2162`，包含 submodule |
| 算法上游参考 | <https://github.com/hku-mars/FAST_LIO> | 不参与本机编译 |

## 4. 网络设计

为 `eth0` 创建 NetworkManager 连接 `mid360-direct`：

- IPv4：`192.168.1.5/24`
- 网关：空
- DNS：空
- `ipv4.never-default=yes`
- 自动连接：开启
- 不改变 `wlan0` 的默认路由

官方示例 MID360 地址为 `192.168.1.12`。实际设备地址可能与序列号有关，因此配置文件先保留官方示例，到货后通过机身序列号、Livox Viewer 2 或设备发现结果确认，再修改 `MID360_config.json`。

## 5. ROS 数据接口

Livox 驱动使用 `msg_MID360_launch.py`，发布自定义 `livox_ros_driver2/CustomMsg`。FAST-LIO2 需要自定义消息中的逐点时间戳完成运动畸变补偿，不能用只发布普通 PointCloud2 的 launch 文件替代。

预期接口：

| 接口 | 生产者 | 消费者 |
|---|---|---|
| `/livox/lidar` | livox_ros_driver2 | FAST_LIO_ROS2 |
| `/livox/imu` | livox_ros_driver2 | FAST_LIO_ROS2 |
| `/Odometry` | FAST_LIO_ROS2 | odom_tf_bridge、重定位 |
| `/cloud_registered` | FAST_LIO_ROS2 | 地图重定位 |
| `/cloud_registered_body` | FAST_LIO_ROS2 | 点云过滤、LaserScan 转换 |

FAST-LIO2 的 `mid360.yaml` 初始使用：

- `lid_topic: /livox/lidar`
- `imu_topic: /livox/imu`
- `lidar_type: 1`
- `scan_line: 4`
- `scan_rate: 10`
- `blind: 0.5`
- `time_sync_en: false`
- `time_offset_lidar_to_imu: 0.0`
- `extrinsic_est_en: true`

雷达安装位姿和时间同步尚未实测，因此外参和时间偏移不能在本阶段标记为最终值。

## 6. 环境加载顺序

交互式 shell 使用以下顺序：

1. `/opt/ros/foxy/setup.bash`
2. Unitree CycloneDDS 工作空间
3. `/home/nvidia/ws_Livox/install/setup.bash`
4. `/home/nvidia/ws_fastlio2/install/setup.bash`
5. `/home/nvidia/Go2_Nav_ws/install/setup.bash`

新增 source 项必须用文件存在判断，避免工作空间尚未构建时导致终端启动报错。

## 7. 验证边界

### 7.1 本次无硬件验收

- 固定 commit 与 submodule 状态正确；
- Livox-SDK2 库和头文件安装到 `/usr/local`；
- `livox_ros_driver2` 在 ROS 2 Foxy 下构建成功；
- `FAST_LIO_ROS2` 在 source Livox 工作空间后构建成功；
- `ros2 pkg list` 能发现 `livox_ros_driver2` 和 `fast_lio`；
- `ros2 pkg executables` 能发现关键节点；
- launch 文件能加载并进入等待雷达状态；
- `eth0` 的静态配置存在，且 Wi-Fi 默认路由未被替换；
- `Go2_Nav_ws` 仍可完整构建。

### 7.2 雷达到货后的实机验收

- `eth0` 有 carrier，Jetson 与 MID360 可以互相到达；
- UDP 端口与 `MID360_config.json` 一致；
- `/livox/lidar` 和 `/livox/imu` 持续发布；
- 点云频率、IMU 频率、QoS 和逐点时间戳正常；
- FAST-LIO2 初始化成功并持续发布 `/Odometry`；
- 静止漂移、运动连续性和点云重影在可接受范围；
- 完成实际 LiDAR-IMU 外参标定后关闭在线外参估计；
- 建图、PCD 保存、PCD 转 2D 地图和 Nav2 链路通过。

## 8. 回滚与安全

- 第三方源码保留 Git commit，可用 `git status` 和 `git rev-parse HEAD` 审计；
- 系统安装的 SDK 通过构建目录中的 `install_manifest.txt` 记录文件；
- 网络配置单独命名为 `mid360-direct`，删除该连接即可回滚；
- 不修改 Wi-Fi 连接和默认路由；
- 修改 `.bashrc` 前保存带时间戳备份；
- 修改 `Go2_Nav_ws` 前依赖 Git commit，禁止覆盖未提交用户改动。

## 9. 交付物

本次交付包括：

1. 本设计文档；
2. 可逐步执行的实施计划；
3. MID360 Jetson Foxy 技术手册；
4. 固定源码版本和实际安装记录；
5. 关键配置模板；
6. 已知问题、解决过程和待硬件验证事项；
7. Git 提交和 GitHub 备份。
