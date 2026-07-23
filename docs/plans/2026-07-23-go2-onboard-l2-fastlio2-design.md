# Go2 机载 L2 接入 FAST-LIO2 设计

**状态：** 已确认

**日期：** 2026-07-23

**目标平台：** Unitree Go2、Jetson Orin NX 16GB、Ubuntu 20.04、ROS 2 Foxy

## 1. 目标与边界

在不改变现有 MID360 主方案的前提下，新增一条独立的实验链路，直接使用
Go2 机载 Unitree 4D LiDAR L2 及其内置 IMU 驱动现有
`Ericsii/FAST_LIO_ROS2`，验证静止初始化、里程计、配准点云和 PCD 建图能力。

本阶段不包含：

- 深度相机融合；
- Nav2 自主运动；
- 自动或手动下发任何机器狗运动指令；
- 替换现有 MID360 配置；
- 修改机器人机载系统程序。

任何需要移动机器狗的动态建图测试，都必须再次取得用户明确同意。

## 2. 雷达型号确认

实机 `/utlidar/cloud` 的逐点时间主间隔约为 `7.73 us`，对应约
`129 kHz` 原始采样；有效点率约为 `60–65k points/s`。该特征与 L2 的
`128k samples/s`、`64k effective points/s` 一致，与 L1 的
`43.2k samples/s`、`21.6k effective points/s` 不符。

实机输入状态：

| 项目 | 实测值 |
|---|---|
| 点云话题 | `/utlidar/cloud` |
| 点云类型 | `sensor_msgs/msg/PointCloud2` |
| 点云频率 | 约 `15.4 Hz` |
| 点云字段 | `x, y, z, intensity, ring, time` |
| 点时间单位 | 秒 |
| 单帧时间跨度 | 约 `0–0.063 s` |
| `ring` 实测值 | `1` |
| IMU 话题 | `/utlidar/imu` |
| IMU 类型 | `sensor_msgs/msg/Imu` |
| IMU 频率 | 约 `250 Hz` |
| 点云/IMU 丢包率 | `0 / 0` |
| 雷达服务版本 | `1.0.0.38` |

## 3. 选定架构

```text
Go2 onboard Unitree 4D LiDAR L2
  ├─ /utlidar/cloud (PointCloud2: x/y/z/intensity/ring/time)
  └─ /utlidar/imu   (sensor_msgs/Imu)
                     │
                     ▼
          Ericsii/FAST_LIO_ROS2
             lidar_type = 2
             timestamp_unit = 0
                     │
        ┌────────────┼──────────────────┐
        ▼            ▼                  ▼
   /Odometry  /cloud_registered  /cloud_registered_body
```

FAST-LIO2 已有 Velodyne `PointCloud2` 预处理入口，其点结构与实机 L2
字段完全一致：

- `float x, y, z, intensity`
- `float time`
- `uint16 ring`

因此第一版只增加 L2 专用配置、输入探针、启动包装器和验证工具，不修改
第三方 FAST-LIO2 源码。只有当短时实机验证证明现有预处理入口无法正确处理
L2 非重复扫描时，才进入第二阶段，增加显式 `UNITREE_L2` 预处理器。

## 4. 工作空间与分支

| 路径 | 用途 |
|---|---|
| `/home/nvidia/unitree_ros2` | Unitree ROS 2 消息与 CycloneDDS 环境 |
| `/home/nvidia/ws_Livox` | 为当前 FAST-LIO2 二进制提供 Livox 消息依赖 |
| `/home/nvidia/ws_fastlio2` | `Ericsii/FAST_LIO_ROS2` |
| `/home/nvidia/Go2_Nav_ws` | 本项目配置、探针、启动与文档 |

开发分支：

```text
feature/go2-onboard-l2-fastlio2
```

该分支以已完成安全控制验证的 `agent/go2-control-verification` 为基线。

## 5. FAST-LIO2 初始参数

L2 专用配置使用以下关键参数：

| 参数 | 初始值 | 原因 |
|---|---:|---|
| `common.lid_topic` | `/utlidar/cloud` | 实机原始 L2 点云 |
| `common.imu_topic` | `/utlidar/imu` | L2 内置 IMU |
| `common.time_sync_en` | `false` | 两个话题来自同一雷达时钟 |
| `preprocess.lidar_type` | `2` | 使用带 `ring/time` 的 PointCloud2 入口 |
| `preprocess.timestamp_unit` | `0` | `time` 字段实测单位为秒 |
| `preprocess.scan_line` | `1` | 实测 `ring` 全部为 `1`，且关闭特征提取 |
| `preprocess.scan_rate` | `15` | 与实机帧率接近；逐点时间存在时仅作后备 |
| `preprocess.blind` | `0.10 m` | L2 官方最小盲区为 0.05 m，保留近场余量 |
| `mapping.det_range` | `30 m` | 与 L2 量程一致 |
| `mapping.extrinsic_est_en` | `false` | 使用 L2 内置雷达/IMU 固定外参 |

FAST-LIO2 的 `extrinsic_T` 定义为“雷达原点在 IMU 坐标系的位置”，用于
`p_imu = R * p_lidar + T`。宇树文档给出 IMU 原点在雷达坐标系的位置为
`[-0.007698, -0.014655, 0.00667] m`，且两坐标轴平行，因此初始值取其逆：

```yaml
extrinsic_T: [0.007698, 0.014655, -0.00667]
extrinsic_R: [1.0, 0.0, 0.0,
              0.0, 1.0, 0.0,
              0.0, 0.0, 1.0]
```

该外参在静止测试中只能验证稳定性，最终仍需通过低速动态数据检查点云重影和
轨迹连续性。

## 6. 输入探针

在启动 FAST-LIO2 前运行只读输入探针，必须通过以下检查：

1. 两个话题均存在且类型正确；
2. 点云包含六个必需字段；
3. `time` 单调或非递减，范围落在合理单帧跨度内；
4. 点云与 IMU 频率达到最低门槛；
5. 两者时间戳属于同一时钟域且没有明显跳变；
6. 原始采样特征仍符合 L2，而不是 L1；
7. 探针不创建任何运动控制 publisher。

## 7. 分级验证

### 7.1 离线静态检查

- 配置文件可被 YAML 解析；
- 关键话题、类型、时间单位和外参值被自动化测试锁定；
- 启动脚本只启动输入探针或 FAST-LIO2，不包含任何 Sport API；
- 现有 Go2 控制安全测试保持通过。

### 7.2 Jetson 静止输入检查

- 机器人保持原地静止；
- 探针持续采样 5–10 秒；
- 确认点云、IMU、字段、频率、时间戳和丢包状态；
- 保存文本报告，不录制运动命令。

### 7.3 FAST-LIO2 静止启动

- 启动前保持机器人静止至少 5 秒；
- 限时运行 30 秒，不保存正式地图；
- `/Odometry`、`/cloud_registered` 和
  `/cloud_registered_body` 持续发布；
- 节点无崩溃、时间回退、IMU 缺失或点云预处理错误；
- 记录静止位置和姿态漂移，作为后续调参依据。

### 7.4 动态验证

动态验证不在本阶段自动执行。获得用户明确授权后，才允许：

- 由用户遥控低速移动，或另行批准受控闭环移动；
- 检查里程计方向、尺度、连续性与点云重影；
- 保存测试 PCD；
- 决定是否需要专用 L2 预处理器。

## 8. 失败处理

| 现象 | 优先检查 |
|---|---|
| 收不到点云 | CycloneDDS 网卡、QoS、`eth0` 地址 |
| 收不到 IMU | `/utlidar/imu` publisher 与 QoS |
| 点云时间为零 | 字段解析、`lidar_type`、`timestamp_unit` |
| 初始化不结束 | 静止时间、IMU 频率、时间戳队列 |
| 静止漂移明显 | IMU 初始偏置、外参方向、重力初始化 |
| 动态点云重影 | 逐点时间、外参、时间偏移、非重复扫描预处理 |
| 节点崩溃 | PointCloud2 字段布局与 PCL 注册结构 |

若现有 Velodyne 入口失败，保留失败数据和日志，先增加回归测试，再实现
`UNITREE_L2` 专用解析；不直接在 Jetson 上做不可追踪的临时修改。

## 9. 交付内容

- L2 FAST-LIO2 配置模板；
- 只读输入探针及其自动化测试；
- 安全启动/停止脚本；
- Jetson 静止验证记录；
- L2 技术手册和复现步骤；
- Git 分支、提交和 GitHub 备份。
