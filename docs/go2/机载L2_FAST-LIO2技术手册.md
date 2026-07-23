# Go2 机载 L2 接入 FAST-LIO2 技术手册

## 1. 当前结论

截至 2026-07-23，Go2 机载雷达已确认是 **Unitree 4D LiDAR L2**。
Jetson 已使用机载 L2 的原始点云和内置 IMU 成功启动
`Ericsii/FAST_LIO_ROS2`：

- L2 输入探针通过；
- FAST-LIO2 完成 IMU 初始化；
- FAST-LIO2 完成地图 KD-tree 初始化；
- `/Odometry`、`/cloud_registered` 和 `/cloud_registered_body`
  均稳定发布；
- 静止 15 秒监测窗口内平移漂移约 `0.0117 m`，偏航漂移约
  `0.0194 rad`（`1.11°`）；
- 尚未执行移动建图和正式 PCD 验收。

本链路是独立实验方案，不替换现有 MID360 主方案。

## 2. 安全边界

本目录中的工具只订阅传感器数据并启动 FAST-LIO2，不包含机器狗运动接口。

必须遵守：

1. 静止探针和静止 FAST-LIO2 测试可以直接运行；
2. 未得到用户再次明确同意前，禁止下发运动命令；
3. 动态建图优先由用户遥控低速完成；
4. 如果以后使用自动闭环移动，必须重新确认距离、速度、场地和急停条件；
5. 测试结束后确认没有遗留 `fastlio_mapping` 进程。

## 3. 硬件型号证据

实机 `/utlidar/cloud` 逐点 `time` 的主间隔为 `7.734 us`，换算原始
采样频率约 `129.3 kHz`；有效点率约 `61.2k points/s`。

| 指标 | 实机 | L2 官方规格 | L1 官方规格 |
|---|---:|---:|---:|
| 原始采样 | 约 129.3k/s | 128k/s | 43.2k/s |
| 有效点率 | 约 61.2k/s | 64k/s | 21.6k/s |
| IMU | 约 247.3 Hz | 内置 IMU | 内置 IMU |

实机特征与 L2 匹配，与 L1 相差约三倍。当前 Go2 官方页面也将标准机载
雷达描述为 L2。

参考来源：

- <https://www.unitree.com/go2/>
- <https://www.unitree.com/cn/mobile/L2/>
- <https://github.com/unitreerobotics/unilidar_sdk2>
- <https://github.com/unitreerobotics/point_lio_unilidar>

## 4. 软件版本

| 组件 | 路径 | 版本 |
|---|---|---|
| Unitree ROS 2 | `/home/nvidia/unitree_ros2` | `668d1ec5a05d1c38d3306bdca7d59f2ba3581a88` |
| CycloneDDS | Unitree ROS 2 工作空间 | `0.10.2` 系列 |
| Livox-SDK2 | `/home/nvidia/Livox-SDK2` | `f5d9375f84efe2b15bc0a052d3e18482ed13adf4` |
| livox_ros_driver2 | `/home/nvidia/ws_Livox/src/livox_ros_driver2` | `13eb05e4e6dd7a765b934d0c5fd6236676a57b49` |
| FAST_LIO_ROS2 | `/home/nvidia/ws_fastlio2/src/FAST_LIO_ROS2` | `2fffc570a25d0df172720bac034fbdb6a13d2162` |
| Go2_Nav_ws 分支 | 本机 Git 工作树 | `feature/go2-onboard-l2-fastlio2` |

FAST-LIO2 工作树中保留两项已记录的部署修改：

- `src/laserMapping.cpp`：ROS 2 Foxy service callback 兼容；
- `config/mid360.yaml`：MID360 独立配置。

L2 配置放在本项目中，不再修改第三方 FAST-LIO2 工作树。

## 5. ROS 输入

| 话题 | 类型 | QoS publisher | 实测频率 |
|---|---|---|---:|
| `/utlidar/cloud` | `sensor_msgs/msg/PointCloud2` | RELIABLE / VOLATILE | 15.399 Hz |
| `/utlidar/imu` | `sensor_msgs/msg/Imu` | RELIABLE / VOLATILE | 247.303 Hz |

点云字段：

| 字段 | PointField datatype |
|---|---:|
| `x` | 7 (`FLOAT32`) |
| `y` | 7 (`FLOAT32`) |
| `z` | 7 (`FLOAT32`) |
| `intensity` | 7 (`FLOAT32`) |
| `ring` | 4 (`UINT16`) |
| `time` | 7 (`FLOAT32`) |

`time` 的单位是秒，单帧跨度约 `0.06265 s`，实测无时间回退。
`ring` 当前全部为 `1`。

## 6. 数据链路

```text
/utlidar/cloud ─┐
                ├─ FAST_LIO_ROS2 ─┬─ /Odometry
/utlidar/imu ───┘                 ├─ /cloud_registered
                                  └─ /cloud_registered_body
```

现有 FAST-LIO2 的 `lidar_type=2` 使用带 `float time` 和 `uint16 ring`
的标准 `PointCloud2` 入口，与 L2 实机字段一致。第一版不修改第三方
预处理器。

## 7. 关键配置

仓库文件：

```text
scripts/go2_l2/config/go2_l2.yaml
```

关键值：

```yaml
common:
  lid_topic: "/utlidar/cloud"
  imu_topic: "/utlidar/imu"
  time_sync_en: false
  time_offset_lidar_to_imu: 0.0

preprocess:
  lidar_type: 2
  scan_line: 1
  blind: 0.10
  timestamp_unit: 0
  scan_rate: 15

mapping:
  det_range: 30.0
  extrinsic_est_en: false
  extrinsic_T: [0.007698, 0.014655, -0.00667]
  extrinsic_R: [1.0, 0.0, 0.0,
                0.0, 1.0, 0.0,
                0.0, 0.0, 1.0]
```

宇树文档给出 IMU 原点在雷达坐标系的位置为
`[-0.007698, -0.014655, 0.00667] m`，两坐标轴平行。FAST-LIO2
需要雷达原点在 IMU 坐标系的位置，因此使用逆向平移。

静止冒烟测试中 `pcd_save_en` 保持 `false`，避免把静止试验误当作正式地图。

## 8. 环境加载顺序

```bash
export UNITREE_INTERFACE=eth0
source /home/nvidia/unitree_ros2/setup.sh
source /home/nvidia/ws_Livox/install/setup.bash
source /home/nvidia/ws_fastlio2/install/setup.bash
```

虽然 L2 输入使用标准 `PointCloud2`，当前 FAST-LIO2 二进制仍链接
`livox_ros_driver2` 消息类型，所以必须加载 Livox 消息工作空间。

ROS 2 Foxy 的 `setup.bash` 会直接读取未定义的可选变量，不能在
`set -u` 生效时 source。仓库启动器会只在加载第三方环境期间执行
`set +u`，加载结束后恢复 `set -u`。

## 9. 输入探针

推荐使用包装器：

```bash
cd /home/nvidia/Go2_Nav_ws
UNITREE_INTERFACE=eth0 \
  bash scripts/go2_l2/run_fastlio2_l2.sh --probe-only
```

报告位置：

```text
/tmp/go2_l2_input_report.json
```

必须满足：

- `detected_model` 为 `L2`；
- `ready_for_fastlio2` 为 `true`；
- `errors` 为空；
- 六个点云字段及类型正确；
- 点云与 IMU 频率在门槛内；
- 没有时间戳回退；
- ROS 时间与 Jetson 系统时间偏差不超过 2 秒。

## 10. 静止启动

保持机器狗静止：

```bash
cd /home/nvidia/Go2_Nav_ws
UNITREE_INTERFACE=eth0 \
  bash scripts/go2_l2/run_fastlio2_l2.sh
```

第一次验证建议使用硬超时：

```bash
timeout --signal=INT --kill-after=5 35 \
  bash scripts/go2_l2/run_fastlio2_l2.sh \
  > /tmp/go2_l2_fastlio2.log 2>&1
```

硬超时返回 `124` 是预期行为。ROS launch 收到 SIGINT 时可能把子节点记录为
`exit code -2`，只要此前已正常发布、日志中没有运行期崩溃栈，并且结束后
没有遗留进程，就不代表算法崩溃。

检查日志：

```bash
grep -E \
  'lidar_type|Node init finished|IMU Initial Done|Initialize the map|ERROR|WARN' \
  /tmp/go2_l2_fastlio2.log
```

检查输出：

```bash
ros2 topic hz /Odometry
ros2 topic hz /cloud_registered
ros2 topic hz /cloud_registered_body
```

## 11. 已知问题与处理

### 11.1 Foxy setup 与 `set -u` 冲突

现象：

```text
/opt/ros/foxy/setup.bash: line 8:
AMENT_TRACE_SETUP_FILES: unbound variable
```

原因是 Foxy 环境脚本直接读取未定义变量。启动器在 source 期间临时关闭
nounset，随后恢复。该问题已有回归测试。

### 11.2 初始化第一帧 `No point`

当前静止测试出现一次：

```text
No point, skip this scan!
```

随后立即完成地图 KD-tree 初始化并稳定发布三个输出，因此判定为初始化边界
帧，不是持续丢点。若以后重复出现或持续出现，需重新检查
`lidar_type`、逐点时间和点云字段。

### 11.3 Jetson 部署目录没有 `.git`

`/home/nvidia/Go2_Nav_ws` 当前是部署目录，不是 Git 工作树。
本次只新增：

```text
/home/nvidia/Go2_Nav_ws/scripts/go2_l2
```

不要在该目录直接执行 `git checkout`。正式版本由开发机分支和 GitHub 保存，
部署时只同步受控文件。

## 12. 下一阶段

尚未验证：

- 移动时里程计尺度与方向；
- 快速转向时的点云去畸变；
- 雷达—IMU 外参在动态数据下的重影；
- 正式 PCD 保存；
- L2 地图接入现有定位与 Nav2；
- 深度相机链路。

动态验证必须在用户再次明确允许机器狗运动后进行。建议先由用户遥控器以
不高于 `0.2–0.3 m/s` 的速度完成短直线和小角度转向，并同步记录
`/utlidar/cloud`、`/utlidar/imu` 与 `/Odometry`。
