# Go2 机载 L2 Point-LIO ROS2 设计

## 1. 状态

- 日期：2026-07-23
- 状态：已批准
- 集成分支：`feature/go2-onboard-l2-pointlio`
- Point-LIO 安装位置：`/home/nvidia/ws_pointlio2`
- 机器人运动边界：没有用户当次明确许可时，不得发送任何运动命令

## 2. 背景与问题

Go2 机载雷达已确认是 Unitree 4D LiDAR L2。现有输入探针已经验证：

- `/utlidar/cloud` 稳定在约 15.4 Hz；
- `/utlidar/imu` 稳定在约 247 Hz；
- 点云逐点时间为秒，单帧跨度约 62.7 ms；
- 点云和 IMU 时间戳连续；
- L2 网络链路没有丢包。

FAST-LIO2 使用通用 Velodyne `PointCloud2` 预处理路径时可以完成静止初始化和
短时静止输出，但在用户遥控低速前进约 5 秒后连续输出
`No Effective Points!`，里程计和 RViz 轨迹随后发散。故障后的只读探针仍然
通过，说明问题位于 LIO 动态处理阶段，不是雷达断流、网线或 RViz 故障。

Unitree 官方 `point_lio_unilidar` 为 L1/L2 提供专用预处理和参数，但该仓库
面向 ROS1 Noetic。Jetson 当前只安装 ROS2 Foxy，因此采用
`dfloreaa/point_lio_ros2`：该项目把 Unitree 官方 L1/L2 Point-LIO 支持移植到
ROS2，并包含 L2 专用 `lidar_type: 5` 路径。

## 3. 目标

1. 在 Jetson 独立工作区安装固定版本的 Point-LIO ROS2。
2. 直接订阅 Go2 已发布的 `/utlidar/cloud` 和 `/utlidar/imu`，不重复启动
   Unitree LiDAR 驱动。
3. 在 RViz2 实时显示配准点云、轨迹和里程计。
4. 第一次动态验证时保留可离线回放的 rosbag 和日志。
5. 保留源码 URL、固定 commit、Foxy 补丁、构建命令和验证记录。
6. 让以后建立独立 Point-LIO 仓库时只需替换源码远端，不改变 Jetson 工作区
   与部署入口。

## 4. 非目标

- 本阶段不创建新的 GitHub 仓库。
- 不把第三方 Point-LIO 源码复制进 `Go2_Nav_ws`。
- 不安装 ROS1 Noetic 或 ROS1/ROS2 bridge。
- 不接入 Nav2、定位或深度相机。
- 静止验证阶段不保存正式 PCD。
- 未取得用户当次明确许可时不进行动态建图测试。
- 所有工具都不得包含机器狗运动发布接口。

## 5. 源码和工作区边界

Point-LIO ROS2 使用独立 colcon 工作区：

```text
/home/nvidia/ws_pointlio2/
├── src/
│   └── point_lio_ros2/
├── build/
├── install/
└── log/
```

安装时记录：

- 上游 URL：`https://github.com/dfloreaa/point_lio_ros2.git`
- 精确 commit；
- 上游许可证：GPL-2.0；
- Jetson/ROS/PCL/Eigen 版本；
- 为 ROS2 Foxy 所做的最小兼容补丁及其校验值。

`Go2_Nav_ws` 只保存部署控制面：

```text
scripts/go2_pointlio/
├── config/go2_l2.yaml
├── rviz/go2_l2_pointlio.rviz
├── tests/
├── run_pointlio_l2.sh
├── record_pointlio_l2.sh
└── README.md
```

未来建立独立 Point-LIO 仓库后，保持
`/home/nvidia/ws_pointlio2/src/point_lio_ros2` 不变，只替换 Git 远端并固定
新 commit。

## 6. 数据流

```text
Go2 onboard DDS
├── /utlidar/cloud ─┐
│                   ├─ pointlio_mapping ─┬─ odometry
└── /utlidar/imu ───┘                    ├─ registered cloud
                                        ├─ path
                                        └─ RViz2

首次动态验证并行记录
├── /utlidar/cloud
├── /utlidar/imu
├── Point-LIO odometry
├── Point-LIO registered cloud（磁盘允许时）
├── /wirelesscontroller
└── /lf/sportmodestate
```

Point-LIO 只订阅传感器和状态话题。启动、录制、监测脚本不导入或调用任何
Unitree 运动服务。

## 7. L2 初始参数

以 ROS2 移植仓库的 Unitree L2 配置和 Unitree 官方 L2 参数为基线：

```yaml
common:
  lid_topic: /utlidar/cloud
  imu_topic: /utlidar/imu
  time_lag_imu_to_lidar: 0.0

preprocess:
  lidar_type: 5
  scan_line: 18
  timestamp_unit: 0
  blind: 0.5

mapping:
  imu_en: true
  extrinsic_est_en: false
  imu_time_inte: 0.004
  acc_norm: 9.81
  fov_degree: 180.0
  det_range: 100.0
  extrinsic_T: [0.007698, 0.014655, -0.00667]
  extrinsic_R: [1.0, 0.0, 0.0,
                0.0, 1.0, 0.0,
                0.0, 0.0, 1.0]

pcd_save:
  pcd_save_en: false
```

第一次验证不通过经验猜测调整多个参数。若出现问题，先用 rosbag 稳定复现，
每次只修改一个有证据支持的参数或兼容点。

## 8. 启动与 RViz2

启动器依次执行：

1. 设定 `UNITREE_INTERFACE=eth0`；
2. 加载 Unitree ROS2、Livox 消息和 Point-LIO 工作区；
3. 运行现有 L2 输入探针；
4. 只有探针通过才启动 Point-LIO；
5. 根据 `RVIZ=true/false` 决定是否启动 RViz2；
6. 前台运行并把日志保存到带时间戳的文件。

RViz2 使用仓库内的专用配置，不复用包含缺失 `rviz_common/Time` 面板的旧
FAST-LIO 配置。Fixed Frame、点云、路径和里程计话题在实机静止测试前通过
Point-LIO 实际发布接口确认。

## 9. 失效处理

监测器只读订阅输入和输出。以下情况判定本轮 SLAM 无效：

- 原始点云或 IMU 超时；
- 里程计输出超时而原始输入仍正常；
- 相邻里程计出现不可能的位移或转角跳变；
- 输出包含连续匹配失败或数值异常；
- Point-LIO 或 RViz2 意外退出。

监测器可以停止 Point-LIO 和录制进程并保留日志，但绝不发送停止、站立或速度
命令给机器狗。机器狗仍由用户遥控，用户负责把摇杆回中并停稳。

## 10. 验证顺序

### 10.1 构建和静态检查

- 固定源码 commit；
- ROS2 Foxy colcon 构建成功；
- 启动器和录制器 Bash 语法检查通过；
- 配置、来源清单和安全边界单元测试通过；
- 启动脚本不包含运动话题、运动服务或速度命令。

### 10.2 静止验证

机器狗保持静止，不需要运动授权：

- 输入探针通过；
- Point-LIO 初始化完成；
- 连续运行至少 60 秒；
- odometry、registered cloud 和 path 持续发布；
- RViz2 正常显示；
- 无 NaN、匹配失败循环或明显静止漂移；
- 结束后没有遗留进程。

### 10.3 动态验证

只有用户再次明确允许后进行：

1. 用户打开遥控器并保持摇杆回中；
2. 先启动 rosbag 和日志；
3. 启动 Point-LIO 并等待静止初始化；
4. 用户低速前进约 5 秒；
5. 用户停稳；
6. 停止 Point-LIO 和 rosbag；
7. 检查轨迹连续性、点云重影、输出频率和日志；
8. 保存 rosbag、报告和校验值。

任何异常都先保留本轮数据并停止 SLAM，不在机器狗仍运动时在线试参数。

## 11. 验收条件

- Jetson 的 `/home/nvidia/ws_pointlio2` 可从文档重新构建。
- 实际运行使用 L2 专用 `lidar_type: 5`。
- 输入话题为 `/utlidar/cloud` 和 `/utlidar/imu`。
- 静止 60 秒验证通过且 RViz2 正常显示。
- 启动和录制工具不包含运动接口。
- 动态测试前能自动建立带时间戳的 rosbag 和日志目录。
- 所有来源、版本、问题、Foxy 补丁和命令写入技术手册。
- 未经用户明确许可没有发生任何由 Jetson 发起的机器狗运动。
