# MID360 前倾 13°统一安装外参设计

日期：2026-07-30

## 1. 目标

MID360 相对 Go2 `base_link` 沿机器人前进方向下倾 13°。系统需要用同一套安装外参完成：

1. FAST-LIO2 三维建图与 PCD 保存；
2. PCD 转二维占据栅格；
3. 基于 PCD 的 ICP 重定位；
4. `odom → base_link` 里程计与 TF 发布；
5. 点云切片、`/scan` 生成和 Nav2 导航。

平移、横滚和偏航保持现有值不变。本次只引入俯仰安装角。

## 2. 当前问题

当前实现隐含以下等价假设：

```text
FAST-LIO body == Nav2 base_link
```

`odom_tf_bridge` 将 FAST-LIO `/Odometry` 的 `body` 直接改名为
`base_link`；点云过滤节点也将 `/cloud_registered_body` 的
`frame_id` 直接改名为 `base_link`，但没有旋转点坐标。

雷达/IMU组件实际相对底盘前倾 13°，因此 `body` 与水平底盘
`base_link` 不再等价。仅在导航阶段修改 `odom_tf_bridge` 会导致建图、
定位和导航使用不同的坐标模型，旧 PCD、二维地图、ICP 结果与机器人
底盘位姿无法一致叠加。

## 3. 坐标与符号约定

- `base_link`：机器人底盘坐标系，`x` 向前、`y` 向左、`z` 向上；
- `body`：FAST-LIO 使用的 MID360 内置 IMU 坐标系；
- 物理安装方向：雷达沿机器人前进方向下倾 13°；
- ROS 旋转约定下：
  - `base_link → body` 的安装俯仰角为 `+13°`；
  - `body → base_link` 为其逆变换 `-13°`；
- 弧度值：

```text
13° = 0.22689280275926285 rad
```

平移、滚转和偏航保持现有值。

## 4. 单一外参源

新增一份共享安装外参配置，作为里程计和点云转换的唯一参数来源：

```yaml
mount:
  translation: [0.0, 0.0, 0.0]
  roll: 0.0
  pitch: 0.22689280275926285
  yaw: 0.0
```

不得在多个节点中分别硬编码 13°。启动文件将同一份配置传给里程计
转换节点与点云转换节点。

FAST-LIO `mid360.yaml` 中的 `extrinsic_T` 和 `extrinsic_R` 表示雷达与
MID360 内置 IMU之间的内部外参，不表示整个 MID360 相对 Go2 底盘的
安装角，因此本方案不使用这两个字段配置 13°。

## 5. 数据流

### 5.1 FAST-LIO 建图

```text
/livox/lidar + /livox/imu
              ↓
          FAST-LIO2
              ├── /Odometry               camera_init → body
              ├── /cloud_registered       camera_init 世界坐标点云
              └── /cloud_registered_body  body 坐标点云
```

FAST-LIO 使用雷达与其内置 IMU的内部外参完成融合。世界点云通过 IMU
重力方向保持水平。保存的 PCD来自 `/cloud_registered`，不在 Livox
驱动层预先旋转点云或 IMU消息。

### 5.2 里程计转换

里程计桥接计算：

```text
T_odom_base = T_odom_body × T_body_base
```

其中 `T_body_base` 是共享安装外参的逆变换。输出：

```text
/odom:
  header.frame_id = odom
  child_frame_id  = base_link

TF:
  odom → base_link
```

位置、姿态、线速度和角速度必须按同一刚体变换处理，不能只改四元数或
只修改 `frame_id`。

### 5.3 点云转换与二维扫描

新增真实点云坐标变换：

```text
/cloud_registered_body (body)
              ↓ T_base_body
/cloud_registered_base (base_link)
              ↓ 高度、距离、体素过滤
/cloud_filtered (base_link)
              ↓ pointcloud_to_laserscan
/scan (base_link)
```

点云过滤节点不再把 `body` 点云直接改名为 `base_link`。高度过滤必须在
完成安装角旋转后的水平 `base_link` 坐标系中执行。

### 5.4 ICP 重定位

ICP保持现有配对：

```text
目标地图：新建的 MID360.pcd（map）
实时扫描：/cloud_registered（camera_init）
初始里程计：/Odometry（camera_init → body）
输出：T_map_odom
```

ICP的实时扫描和初始里程计都来自同一个 FAST-LIO坐标模型，因此不在
ICP输入中混入转换后的 `/odom`。`transform_fusion` 再组合：

```text
T_map_base = T_map_odom × T_odom_base
```

### 5.5 Nav2

Nav2使用：

```text
map → odom → base_link
                    └── /scan (base_link)
```

全局地图使用新 PCD转换出的 `MID360_map.yaml/.pgm`，局部代价地图使用
已转换到水平底盘坐标系的 `/scan`。

## 6. 新地图生成流程

1. 停止 ICP、Nav2和旧地图服务器；
2. 启动 Livox驱动和 FAST-LIO建图；
3. 验证新外参下 `base_link` 水平、点云墙面竖直、地面水平；
4. 操作机器狗遍历环境；
5. 调用 `/map_save` 保存并覆盖 `MID360.pcd`；
6. 使用 `pcd_to_occupancy` 生成新的 `MID360_map.pgm/.yaml`；
7. 关闭建图，启动 FAST-LIO里程计、ICP和 Nav2；
8. 在多个初始位置执行重定位验证；
9. 最后进行单点和多点导航实测。

覆盖旧地图前应创建带时间戳的备份，以便快速回到已验证基线。

## 7. 故障保护

- 外参配置缺失、角度非有限数或四元数无法归一化时，转换节点拒绝启动；
- 点云输入 `frame_id` 不是预期的 `body` 时停止输出并记录错误；
- TF树存在重复父节点时，不启动 Nav2；
- `/odom`、`/scan` 或 `map → base_link` 超时后禁止发送导航速度；
- 地图与外参版本不匹配时，在启动检查中明确失败；
- 真机测试前先做静止状态验证，不发送导航目标。

## 8. 验证标准

### 静态检查

- 共享配置中只有一个 13°定义；
- FAST-LIO内部 `extrinsic_R/T` 未被安装角覆盖；
- `/cloud_registered_base` 的点坐标发生真实旋转，不是仅改帧名；
- TF树中 `base_link` 没有重复父节点。

### 运行检查

- 静止水平地面上，`base_link` 的 roll/pitch接近 0；
- `/scan` 与二维地图墙体重合；
- `map → odom → base_link` 连续且无跳变；
- ICP MSE低于配置阈值，并且连续修正不被位移/角度门限拒绝；
- Web、RViz中的机器人图标、实时扫描和地图处于同一位置。

### 真机检查

- 原地旋转时机器人中心没有明显平移漂移；
- 直行路径与地图通道方向一致；
- 单点导航成功后再测试 `/FollowWaypoints` 多点导航；
- 运动链路继续使用已验证的外载发送器、内载网关和 Unitree
  `SportClient`，本次外参调整不修改底盘网关协议。

## 9. 不采用的方案

### 仅修改 `odom_tf_bridge`

建图点云、点云切片和导航里程计使用不同坐标模型，已导致旧地图与机器人
位姿错位。

### 修改 Livox驱动输出

必须同时正确旋转点云、加速度、角速度和协方差，容易破坏 FAST-LIO输入
假设，风险高。

### 将 13°写入 FAST-LIO内部 `extrinsic_R`

该字段描述雷达相对内置 IMU的内部外参，不能表达整个传感器组件相对机器
狗底盘的安装姿态。
