# MID360 直连 Jetson 技术手册

> 适用环境：Jetson Orin NX 16GB、Ubuntu 20.04 ARM64、ROS 2 Foxy、Livox
> MID360、`/home/nvidia/Go2_Nav_ws`。
> 本手册记录 2026-07-23 已完成的软件准备，以及雷达到货后仍需完成的实机验收。

## 1. 结论与系统边界

MID360 连接外置 Jetson 的 `eth0`，不要接宇树机载电脑。Jetson 同时承担
Livox 驱动、FAST-LIO2 建图和 Go2 导航工作区；`wlan0` 继续用于 SSH 和日常网络。

```text
MID360 ──专用网线── Jetson eth0  192.168.1.5/24
                           │
                           ├── Livox-SDK2
                           ├── livox_ros_driver2
                           ├── FAST_LIO_ROS2
                           └── Go2_Nav_ws

Jetson wlan0 ── Wi-Fi/LAN ── SSH、GitHub、互联网
```

`eth0` 配置不设网关，并启用 `ipv4.never-default`，因此不会抢占 Wi-Fi 默认路由。

## 2. 已安装目录与固定版本

| 组件 | Jetson 目录 | 固定版本 |
|---|---|---|
| 主项目 | `/home/nvidia/Go2_Nav_ws` | GitHub `ZhenqinHuang/Go2_Nav_ws` |
| Livox-SDK2 | `/home/nvidia/Livox-SDK2` | `f5d9375f84efe2b15bc0a052d3e18482ed13adf4`（v1.3.1） |
| livox_ros_driver2 | `/home/nvidia/ws_Livox/src/livox_ros_driver2` | `13eb05e4e6dd7a765b934d0c5fd6236676a57b49` |
| FAST_LIO_ROS2 | `/home/nvidia/ws_fastlio2/src/FAST_LIO_ROS2` | `2fffc570a25d0df172720bac034fbdb6a13d2162`（`ros2` 分支） |
| ikd-Tree 子模块 | FAST-LIO 仓库内 | `e2e3f4e9d3b95a9e66b1ba83dc98d4a05ed8a3c4` |

源码来源：

- [Livox-SDK2](https://github.com/Livox-SDK/Livox-SDK2)
- [livox_ros_driver2](https://github.com/Livox-SDK/livox_ros_driver2)
- [Ericsii/FAST_LIO_ROS2](https://github.com/Ericsii/FAST_LIO_ROS2)
- [hku-mars/FAST_LIO](https://github.com/hku-mars/FAST_LIO)（算法上游参考，不作为本机直接构建源）

固定提交而不是跟随最新分支，可以避免日后上游变化导致无法复现。本仓库不复制第三方
源码，只保存来源、提交号、配置模板和必要兼容补丁。

## 3. 网络规划

| 对象 | 接口/地址 | 用途 |
|---|---|---|
| Jetson | `eth0` / `192.168.1.5/24` | MID360 专用链路 |
| MID360 | 当前模板为 `192.168.1.12` | 到货后以设备实际地址为准 |
| Jetson | `wlan0` / DHCP | SSH 和外网，保留默认路由 |

NetworkManager 连接名为 `mid360-direct`，关键参数如下：

```text
connection.interface-name = eth0
connection.autoconnect = yes
connection.autoconnect-priority = 100
ipv4.method = manual
ipv4.addresses = 192.168.1.5/24
ipv4.gateway = 空
ipv4.never-default = yes
ipv6.method = disabled
```

雷达未接线时 `eth0` 没有 carrier，NetworkManager 可能不会把静态地址显示为活动地址；
配置仍已保存，接线后会自动启用。不要为“让地址显示出来”给该连接添加默认网关。

## 4. 一键复现安装

### 4.1 先检查平台

```bash
cat /etc/os-release
dpkg --print-architecture
test -f /opt/ros/foxy/setup.bash
```

脚本有平台保护，仅允许 Ubuntu 20.04、ARM64 和 ROS 2 Foxy。执行前确认
`/home/nvidia/Go2_Nav_ws` 中没有需要保留的未提交改动。

### 4.2 安装固定版本软件栈

```bash
cd /home/nvidia/Go2_Nav_ws
sudo -v
bash scripts/mid360/install_mid360_stack.sh 2>&1 | \
  tee .codex_backups/mid360-install-replay.log
```

脚本会：

1. 安装构建依赖；
2. 检出并构建固定版本的 Livox-SDK2；
3. 编译 `livox_ros_driver2`；
4. 初始化 FAST-LIO 的 ikd-Tree 子模块；
5. 应用 ROS 2 Foxy 服务回调兼容补丁；
6. 安装 MID360 配置并编译 FAST-LIO。

第三方仓库存在未知修改时脚本会停止，不会直接覆盖。

### 4.3 配置专用网卡

```bash
cd /home/nvidia/Go2_Nav_ws
sudo bash scripts/mid360/configure_mid360_network.sh
nmcli connection show mid360-direct
ip route show default
```

最后一条默认路由应继续指向 `wlan0`。

### 4.4 环境加载顺序

本机 `~/.bashrc` 已按以下顺序加载：

```bash
source /opt/ros/foxy/setup.bash
# Unitree CycloneDDS 环境（本机已有）
test -f ~/ws_Livox/install/setup.bash && source ~/ws_Livox/install/setup.bash
test -f ~/ws_fastlio2/install/setup.bash && source ~/ws_fastlio2/install/setup.bash
test -f ~/Go2_Nav_ws/install/setup.bash && source ~/Go2_Nav_ws/install/setup.bash
```

每个工作空间都做文件存在判断，未编译时不会让新终端报错。

## 5. 关键配置

仓库中的可复现模板：

- `scripts/mid360/config/MID360_config.json`
- `scripts/mid360/config/mid360.yaml`
- `scripts/mid360/patches/fast_lio_ros2_foxy_service_callback.patch`

安装后的运行配置：

- `/home/nvidia/ws_Livox/src/livox_ros_driver2/config/MID360_config.json`
- `/home/nvidia/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml`

当前 ROS 接口为：

| 数据 | 话题 |
|---|---|
| Livox 自定义点云 | `/livox/lidar` |
| MID360 内置 IMU | `/livox/imu` |
| FAST-LIO 里程计 | `/Odometry` |
| FAST-LIO 世界系点云 | `/cloud_registered` |
| FAST-LIO 机体系点云 | `/cloud_registered_body` |

`mid360.yaml` 中 `preprocess.lidar_type` 必须为 `1`，与 Livox 自定义消息对应。
当前 `extrinsic_est_en: true` 只用于实机初期联调；完成 LiDAR-IMU 外参标定后，应写入
最终 `extrinsic_T`、`extrinsic_R` 并关闭在线外参估计。

## 6. 雷达到货后的首次接线

### 6.1 接线和地址确认

1. MID360 数据线直连 Jetson `eth0`，按设备说明提供合规电源。
2. 等待接口载波后检查：

   ```bash
   cat /sys/class/net/eth0/carrier
   ip -br address show eth0
   nmcli connection show --active
   ```

3. 预期 carrier 为 `1`，`eth0` 为 `192.168.1.5/24`。
4. 从设备标签、Livox 工具或网络抓包确认 MID360 的实际 IP。不要仅凭序列号猜测。
5. 若不是 `192.168.1.12`，同时更新：

   ```text
   /home/nvidia/Go2_Nav_ws/scripts/mid360/config/MID360_config.json
   /home/nvidia/ws_Livox/src/livox_ros_driver2/config/MID360_config.json
   /home/nvidia/Go2_Nav_ws/src/Go2_time_sync/config/ptp_sync.yaml
   ```

   JSON 中修改 `lidar_configs[].ip`；Jetson 的所有 `host_net_info` 地址仍保持
   `192.168.1.5`。修改仓库模板后应提交到 Git，保证下一次安装能复现。

6. 检查连通性：

   ```bash
   ping -I eth0 -c 3 <MID360实际IP>
   ip route show default
   ```

   即使设备禁用 ICMP，后续驱动能收到 UDP 点云也可判定链路正常。默认路由仍应走
   `wlan0`。

### 6.2 启动驱动

终端 A：

```bash
source /opt/ros/foxy/setup.bash
source /home/nvidia/ws_Livox/install/setup.bash
ros2 launch livox_ros_driver2 msg_MID360_launch.py
```

终端 B：

```bash
source /opt/ros/foxy/setup.bash
source /home/nvidia/ws_Livox/install/setup.bash
ros2 topic list | grep livox
ros2 topic hz /livox/lidar
ros2 topic hz /livox/imu
ros2 topic echo /livox/imu --once
```

点云和 IMU 必须持续发布，时间戳应递增。

### 6.3 启动 FAST-LIO

终端 C：

```bash
source /opt/ros/foxy/setup.bash
source /home/nvidia/ws_Livox/install/setup.bash
source /home/nvidia/ws_fastlio2/install/setup.bash
ros2 launch fast_lio mapping.launch.py \
  config_path:=/home/nvidia/ws_fastlio2/src/FAST_LIO_ROS2/config \
  config_file:=mid360.yaml \
  rviz:=true
```

终端 D：

```bash
ros2 topic hz /Odometry
ros2 topic hz /cloud_registered
ros2 topic echo /Odometry --once
```

在 RViz2 中缓慢移动设备，检查点云不分层、不重影、轨迹不跳变。之后再进入外参标定、
建图和 Nav2 联调。

### 6.4 PTP 时间同步

当前准备了 `Go2_time_sync`，但没有雷达时无法验证 PTP。先确认原始点云和 IMU稳定，
再单独启用：

```bash
cd /home/nvidia/Go2_Nav_ws
sudo bash src/Go2_bringup/time_sync_start.sh
```

启用前必须确认配置中的雷达 IP 和 `eth0` 正确。不要把“脚本能启动”当成同步成功；
应同时检查 `ptp4l` 日志和实际消息时间戳。

## 7. 验收清单

### 7.1 无雷达时可执行

```bash
cd /home/nvidia/Go2_Nav_ws
bash scripts/mid360/verify_mid360_preparation.sh
```

预期结果为 `failures=0`。雷达未接时：

```text
[PENDING] eth0 carrier and real MID360 data (hardware not connected)
```

这是正常的硬件待办，不是安装失败。

### 7.2 实机验收

- [ ] `eth0` carrier 为 1，地址为 `192.168.1.5/24`
- [ ] MID360 实际 IP 已写入驱动和时间同步配置
- [ ] Wi-Fi 默认路由未变化，SSH 不掉线
- [ ] 驱动稳定发布 `/livox/lidar` 与 `/livox/imu`
- [ ] FAST-LIO 稳定发布 `/Odometry` 与点云
- [ ] 静止时里程计不明显漂移
- [ ] 移动时点云无明显双影、轨迹无跳变
- [ ] LiDAR-IMU 外参完成标定并固化
- [ ] 长时间建图前调整 PCD 分片策略，避免 `interval: -1` 占用过多内存
- [ ] PTP 若启用，已用日志和消息时间戳确认同步效果

## 8. 常见问题

### 驱动报 bind failed

先检查 `ip -br address show eth0`。无载波时静态 IP 可能尚未激活；接好雷达后运行：

```bash
sudo nmcli connection up mid360-direct
```

再检查 JSON 中所有 Jetson 地址是否为 `192.168.1.5`，以及 UDP 端口是否被其他进程占用：

```bash
sudo ss -lunp | grep -E '56101|56201|56301|56401|56501'
```

### 驱动启动但没有点云

核对 MID360 实际 IP、网线载波、设备供电和 JSON 的 `lidar_configs[].ip`。用以下命令
确认数据包是否到达 Jetson：

```bash
sudo tcpdump -ni eth0 udp
```

若有 UDP 包而 ROS 无话题，再检查驱动配置路径、ROS overlay 加载和防火墙。

### FAST-LIO 在 Foxy 编译失败

本次遇到 `std_srvs/Trigger` 请求回调类型不兼容。仓库补丁把
`Request::ConstSharedPtr` 改为 Foxy 接受的 `Request::SharedPtr`。检查：

```bash
bash /home/nvidia/Go2_Nav_ws/scripts/mid360/tests/test_fast_lio_foxy_compat.sh \
  /home/nvidia/ws_fastlio2/src/FAST_LIO_ROS2/src/laserMapping.cpp
```

不要换成未经验证的任意 FAST-LIO fork。

### 新终端找不到 ROS 包

```bash
source /opt/ros/foxy/setup.bash
source ~/ws_Livox/install/setup.bash
source ~/ws_fastlio2/install/setup.bash
source ~/Go2_Nav_ws/install/setup.bash
ros2 pkg prefix livox_ros_driver2
ros2 pkg prefix fast_lio
```

### SSH 因网络配置中断

保持 Wi-Fi 已连接，不给 `eth0` 设置 gateway。若默认路由异常：

```bash
sudo nmcli connection down mid360-direct
ip route show default
```

然后依据备份恢复 NetworkManager 配置。

## 9. 备份与回滚

本次备份位于：

```text
/home/nvidia/Go2_Nav_ws/.codex_backups/mid360-prep-20260723/
├── prechange/
│   ├── bashrc
│   ├── system-inventory.txt
│   ├── networkmanager-connections.txt
│   └── maintained-files.tar.gz
├── vendor-defaults/
└── postchange/
    ├── install.log
    ├── install-retry-foxy-patch.log
    ├── livox-smoke.log
    ├── livox-smoke-temporary-ip.log
    ├── fastlio-smoke.log
    ├── go2-build-test.log
    ├── verification.log
    └── final-verification.log
```

恢复 shell 配置：

```bash
test -f /home/nvidia/Go2_Nav_ws/.codex_backups/mid360-prep-20260723/prechange/bashrc
cp /home/nvidia/Go2_Nav_ws/.codex_backups/mid360-prep-20260723/prechange/bashrc \
  /home/nvidia/.bashrc
```

确认第一条检查成功后再执行复制。恢复网络：

```bash
sudo nmcli connection down mid360-direct 2>/dev/null || true
sudo nmcli connection delete mid360-direct
```

删除软件工作空间前先确认其中没有实机标定结果、地图或其他人工修改。第三方原始配置在
`vendor-defaults/`，主项目受 Git 版本控制。

## 10. 本次验证结论

2026-07-23 的离线验收为：13 项通过、0 项失败、1 项待硬件。已验证固定源码版本、
SDK 库和头文件、ROS 包可见性、JSON/YAML、Foxy 兼容补丁、NetworkManager 配置和
Wi-Fi 默认路由；驱动与 FAST-LIO 均完成无硬件限时启动，Go2 工作区完整编译通过。

唯一未完成项是雷达接入后的 carrier、真实点云/IMU、外参、时间同步和建图质量验证。
这些项目必须在 MID360 到货并完成机械安装后按第 6、7 节执行。
