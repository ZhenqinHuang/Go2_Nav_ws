# Go2 Nav Workspace

本 README 作为 `Go2_Nav_ws` 项目根目录的执行清单，按 `2026-04-24`、`2026-04-27`、`2026-04-28` 三个阶段整理当前导航集成任务，方便按照统一顺序推进、验证和打包。

## 1. 当前工程现状

当前仓库内已确认存在的关键模块和入口：

- 时间同步：
  - `src/Go2_bringup/time_sync_start.sh`
  - `src/Go2_time_sync/launch/ptp_sync.launch.py`
  - `src/Go2_time_sync/config/ptp_sync.service`
- 传感器与导航前置链路：
  - `src/Go2_bringup/go2_nav_start.sh`
  - `src/Go2_localization/odom_tf_bridge`
  - `src/Go2_perception/pointcloud_to_laserscan`
- 文档说明：
  - `src/README.md`
  - `src/Go2_bringup/README.md`

当前仓库内尚未看到明确落地文件的部分：

- HDL Localization 集成入口
- Nav2 专用启动脚本
- Nav2 数据验证脚本
- WebSocket 启动脚本
- 到点播报/文本朗读节点
- 一键启动总脚本

因此下面执行 List 会同时标出：

- 已有入口：可直接使用
- 待新增：需要在对应日期内补齐

## 2. 推荐总执行顺序

### 2.1 编译

```bash
cd /home/wangzhenjie/Go2_Nav_ws
colcon build --symlink-install
source /home/wangzhenjie/Go2_Nav_ws/install/setup.bash
```

### 2.2 启动时间同步

工程已有脚本：

```bash
sudo bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/time_sync_start.sh
```

### 2.3 启动传感器与 Nav2 前置数据流

工程已有脚本：

```bash
bash /home/wangzhenjie/Go2_Nav_ws/src/Go2_bringup/go2_nav_start.sh
```

该脚本当前负责拉起并检查：

- Livox MID360 驱动
- FAST-LIO2
- `/Odometry -> /odom`
- `odom -> base_link`
- `/cloud_registered_body -> /scan`

### 2.4 基础链路检查

建议至少执行以下检查：

```bash
ros2 topic list
ros2 topic hz /odom
ros2 topic hz /scan
ros2 topic hz /tf
ros2 run tf2_ros tf2_echo odom base_link
```

HDL Localization 接入后，再补：

```bash
ros2 run tf2_ros tf2_echo map odom
```

## 3. Day2 执行 List (`2026-04-24`)

### 3.1 重定位算法加载

- 集成 HDL Localization。
- 明确 HDL Localization 输入输出：
  - 输入：点云、地图、初始位姿
  - 输出：`map -> odom`
- 若 HDL Localization 独立于当前脚本启动，建议新增：
  - `src/Go2_bringup/hdl_localization_start.sh`

完成标准：

- 能稳定发布 `map -> odom`
- 与当前 `odom -> base_link` 组成 `map -> odom -> base_link`

### 3.2 TF 链路验证

验证链路：

- `map -> odom -> base_link`

重点检查项：

- 时间戳是否连续
- `/tf` 发布频率是否稳定
- `odom -> base_link` 是否跳变
- `map -> odom` 是否存在大幅漂移或抖动

建议命令：

```bash
ros2 topic hz /tf
ros2 topic echo /tf --once
ros2 run tf2_ros tf2_echo map odom
ros2 run tf2_ros tf2_echo odom base_link
```

### 3.3 Nav2 接入

待新增脚本：

- `src/Go2_bringup/nav2_check.sh`
  - 验证 `/odom`
  - 验证 `/tf`
  - 验证 `/scan`
- `src/Go2_bringup/nav2_start.sh`
  - 启动 HDL Localization
  - 启动 Nav2
  - 加载地图和参数

Nav2 接入前必须确认：

- `/odom` 正常
- `map -> odom -> base_link` 正常
- `/scan` 数据连续
- costmap 参数和 frame 配置一致

### 3.4 版本管理

- 将 Nav2 相关包、配置、脚本纳入工程
- 打包新增文件并上传

建议本阶段至少纳入版本管理的内容：

- Nav2 启动脚本
- Nav2 参数文件
- 地图文件
- HDL Localization 配置
- 验证脚本

## 4. Day3 执行 List (`2026-04-27`)

### 4.1 Nav2 参数调整

- 一层室内各条线路逐条验证
- 根据实际效果调整：
  - 局部代价地图参数
  - 全局代价地图参数
  - 控制器参数
  - 规划器参数
  - 恢复行为参数

重点记录：

- 哪些路线可稳定到达
- 哪些位置容易振荡、绕远、卡死
- 调参前后效果对比

### 4.2 代码集成

目标：统一启动方式，减少人工分步操作。

建议脚本归类如下：

- 时间同步脚本：
  - 已有 `src/Go2_bringup/time_sync_start.sh`
- 传感器启动脚本：
  - 当前可继续使用 `src/Go2_bringup/go2_nav_start.sh`
  - 如后续职责过重，可拆成独立 `sensor_start.sh`
- Nav2 启动脚本：
  - 待新增 `src/Go2_bringup/nav2_start.sh`
- Web 启动脚本：
  - 待新增 `src/Go2_bringup/web_start.sh`

本阶段产出建议：

- 统一脚本命名
- 统一日志目录
- 统一环境变量入口
- 统一 source 顺序

### 4.3 版本管理

- 集成后的脚本和配置统一打包上传
- 补齐 README 和目录说明

## 5. Day4 执行 List (`2026-04-28`)

### 5.1 系统集成与稳定性验证

- 从 Web 界面发送导航点
- 验证机器人是否能完整到达目标点
- 继续调试 Nav2 参数并优化

建议重点验证：

- 连续多点导航是否稳定
- 长时间运行是否出现 TF 断链
- costmap 是否出现异常膨胀或障碍滞留
- 到点判定是否稳定

### 5.2 新功能增加

待新增能力：

- 到达目标点播放音频文件
- 订阅某个话题并朗读文本信息

建议拆分为两个独立节点：

- `audio_player_node`
- `tts_subscriber_node`

### 5.3 一键启动

待新增脚本：

- `src/Go2_bringup/all_in_one_start.sh`

建议整合顺序：

1. 时间同步
2. 传感器链路
3. HDL Localization
4. Nav2
5. WebSocket
6. 音频播报相关节点

### 5.4 开机自启动

当前仓库已有可参考文件：

- `src/Go2_time_sync/config/ptp_sync.service`

建议最终补齐：

- 导航主流程 systemd service
- Web 桥接 service
- 开机后延时启动策略

### 5.5 版本管理

- 打包上传全部新增文件
- 固化最终启动方式和部署说明

## 6. 建议补齐的文件清单

按当前计划，建议新增或确认以下文件：

- `README.md`
- `src/Go2_bringup/hdl_localization_start.sh`
- `src/Go2_bringup/nav2_check.sh`
- `src/Go2_bringup/nav2_start.sh`
- `src/Go2_bringup/web_start.sh`
- `src/Go2_bringup/all_in_one_start.sh`
- Nav2 参数文件
- HDL Localization 参数文件
- 地图文件
- 音频播报节点
- 文本朗读节点

## 7. 每日交付物检查

### Day2

- HDL Localization 可启动
- `map -> odom -> base_link` 链路闭合
- Nav2 验证脚本初版
- Nav2 启动脚本初版
- 新增文件已打包上传

### Day3

- 一层室内线路导航验证完成
- 脚本分类清晰
- 统一工程集成完成
- 新增文件已打包上传

### Day4

- Web 发点导航可运行
- 音频播报与文本朗读可运行
- 一键启动可运行
- 开机自启动方案可落地
- 新增文件已打包上传

## 8. 当前最小可运行命令

在当前仓库已存在文件基础上，可直接执行的最小链路如下：

```bash
cd /home/wangzhenjie/Go2_Nav_ws
colcon build --symlink-install
source install/setup.bash
sudo bash src/Go2_bringup/time_sync_start.sh
```

另开终端：

```bash
cd /home/wangzhenjie/Go2_Nav_ws
source install/setup.bash
bash src/Go2_bringup/go2_nav_start.sh
```

然后检查：

```bash
ros2 topic hz /odom
ros2 topic hz /scan
ros2 run tf2_ros tf2_echo odom base_link
```

后续在此基础上继续补 HDL Localization、Nav2、Web 和一键启动入口。
