# Jetson NX 到 Go2：外载—内载控制链路部署联调日志

> 文档版本：2026-07-29  
> 正常路径：外载 Nav2/Web → UDP → 内载 `go2_cmd_gateway` → Unitree `SportClient` → Go2  
> 原理与接口：[Jetson NX 到 Go2 控制链路架构与接口说明](Jetson_NX到Go2_控制链路架构与接口.md)  
> GitHub：<https://github.com/ZhenqinHuang/go2-integrated-web-console>

## 0. 使用方法

本 Runbook 按执行顺序编写：

1. 第 1～5 节：准备、网络、代码和服务安装；
2. 第 6～8 节：无运动检查，确认数据链路；
3. 第 9 节：Web、ROS CLI、Nav2 和 HTTP 接口；
4. 第 10 节：现场低速与 Nav2 实机验收；
5. 第 11～14 节：排障、恢复、回退和日志记录。

命令默认在 Ubuntu Bash 中执行。命令前会注明运行位置：

- `[操作电脑]`
- `[外载]`
- `[内载]`

## 1. 安全前提

### 1.1 不允许运动的状态

以下任一条件存在时，只做网络、编译、服务和状态检查，不得 Arm：

- 机器人仍在充电器上；
- 机器人被吊起或四脚不能稳定着地；
- 前方、侧方有人或障碍物；
- 急停条件不明确；
- 内载、外载或下位机的 IP/网卡尚未确认；
- `192.168.123.18` 或 `192.168.123.161` 路由不是 `eth0`；
- 同时运行了 UDP sender 和旧 DDS bridge；
- 网关状态不明确；
- 现场人员无法立即执行 Disarm。

### 1.2 运动测试前必须准备

- 机器人离开充电器；
- 四脚稳定着地；
- 前方至少保留 1 米安全空间；
- 操作员能接触急停或能立即 Disarm；
- 首次速度不高于 `0.1 m/s`；
- 首次持续时间不超过 4 秒；
- 另开一个终端准备 Disarm。

### 1.3 紧急归零与 Disarm

正常情况下在外载执行：

```bash
cd /home/nvidia/Go2_Nav_ws
bash src/Go2_bringup/go2_gateway_disarm.sh
```

等价 ROS 命令：

```bash
source /opt/ros/foxy/setup.bash
source /home/nvidia/Go2_Nav_ws/install/setup.bash

ros2 service call \
  /go2_cmd_vel_gateway/arm \
  std_srvs/srv/SetBool \
  "{data: false}"
```

如果外载 ROS 不可用，在内载执行：

```bash
sudo systemctl stop go2-cmd-gateway.service
```

内载服务收到 SIGTERM 后会调用 `StopMove()` 再退出。

## 2. 现场资产表

### 2.1 设备与 IP

| 设备 | 用户用途 | 地址 |
|---|---|---:|
| 外载 Jetson NX `wlan0` | SSH、Web、默认路由 | `192.168.0.101/24` |
| 外载 Jetson NX `eth0` | Go2 控制专网 | `192.168.123.5/24` |
| 外载 Jetson NX `eth1` | MID360S | `192.168.1.5/24` |
| 内载 Ubuntu `eth0` | UDP 网关与 DDS | `192.168.123.18/24` |
| Go2 下位机 | Unitree DDS | `192.168.123.161/24` |
| MID360S | 点云/IMU | `192.168.1.158/24` |

账号和密码不写入 GitHub。现场凭据记录在受控飞书文档或密码管理工具中。

### 2.2 代码位置

独立仓库结构：

```text
go2-integrated-web-console/
  config/
  docs/
  frontend/
  go2_control_gateway/
  internal_gateway/
  launch/
  scripts/
  systemd/
  test/
```

在完整导航工作空间中，对应位置：

```text
/home/nvidia/Go2_Nav_ws/src/Go2_control_gateway
```

也就是说：

```text
独立仓库 config/                  → Go2_Nav_ws/src/Go2_control_gateway/config/
独立仓库 go2_control_gateway/     → Go2_Nav_ws/src/Go2_control_gateway/go2_control_gateway/
独立仓库 internal_gateway/        → Go2_Nav_ws/src/Go2_control_gateway/internal_gateway/
```

### 2.3 服务和进程

| 位置 | 服务/进程 | 是否随系统启动 |
|---|---|---|
| 外载 | `go2-console.service` | 是 |
| 外载 | `go2-console-rosbridge.service` | 是 |
| 外载 | `go2_cmd_vel_udp_sender` | 由 `run_nav2.sh` 启动 |
| 内载 | `go2-cmd-gateway.service` | 是 |

## 3. 阶段 A：连接外载 Jetson

### 3.1 操作电脑确认自身网络

`[操作电脑 / Windows PowerShell]`

```powershell
ipconfig
Test-Connection 192.168.0.101 -Count 2
Test-NetConnection 192.168.0.101 -Port 22
Test-NetConnection 192.168.0.101 -Port 8080
```

预期：

- 操作电脑在 `192.168.0.0/24` 或存在到该网段的路由；
- `192.168.0.101:22` 可访问；
- Web 服务安装后 `192.168.0.101:8080` 可访问。

SSH：

```powershell
ssh nvidia@192.168.0.101
```

如果 ping 和 SSH 都失败：

1. 检查电脑是否连接到与外载相同的局域网；
2. 查看电脑是否被 VPN 改写路由；
3. 确认外载 `wlan0` 是否仍为 `192.168.0.101`；
4. 不要在未知网络状态下修改外载 `eth0` 或 `eth1`。

### 3.2 当前文档编写时的连接记录

- 2026-07-28：曾从局域网确认外载 SSH、Web 和 systemd 服务；
- 2026-07-29：重新读取 `192.168.0.101` 时 SSH/ICMP 超时。

因此重新开始现场工作时，本节必须重新执行，不能仅依赖前一天记录。

## 4. 阶段 B：配置并验证网络

## 4.1 外载接口识别

`[外载]`

```bash
ip -br link
ip -br -4 address
nmcli -f NAME,UUID,TYPE,DEVICE connection show
nmcli -f NAME,DEVICE,TYPE,IP4.ADDRESS,IP4.GATEWAY connection show --active
```

确认：

- `eth0` 是经 USB 转网口连接内载的接口；
- `eth1` 是直接连接 MID360S 的接口；
- `wlan0` 是局域网接口。

不要仅根据 Linux 枚举顺序猜接口。必要时逐根拔插网线并观察：

```bash
ip monitor link
```

## 4.2 外载持久化配置

当前约定连接名：

```text
go2-direct     → eth0
mid360-direct  → eth1
```

先检查连接是否存在：

```bash
nmcli connection show go2-direct
nmcli connection show mid360-direct
```

如果连接已经存在，修改：

```bash
sudo nmcli connection modify go2-direct \
  connection.interface-name eth0 \
  ipv4.method manual \
  ipv4.addresses 192.168.123.5/24 \
  ipv4.gateway "" \
  ipv4.never-default yes \
  ipv6.method disabled

sudo nmcli connection modify mid360-direct \
  connection.interface-name eth1 \
  ipv4.method manual \
  ipv4.addresses 192.168.1.5/24 \
  ipv4.gateway "" \
  ipv4.never-default yes \
  ipv6.method disabled
```

如果连接不存在，新增：

```bash
sudo nmcli connection add \
  type ethernet ifname eth0 con-name go2-direct \
  ipv4.method manual ipv4.addresses 192.168.123.5/24 \
  ipv4.never-default yes ipv6.method disabled

sudo nmcli connection add \
  type ethernet ifname eth1 con-name mid360-direct \
  ipv4.method manual ipv4.addresses 192.168.1.5/24 \
  ipv4.never-default yes ipv6.method disabled
```

重新激活：

```bash
sudo nmcli connection up go2-direct
sudo nmcli connection up mid360-direct
```

如果设备没有载波，`nmcli connection up` 可能失败；接好网线和上电后再执行。

不要删除名称不确定的连接。不要用临时 `ip route add` 掩盖持久配置错误。

## 4.3 外载路由验收

```bash
ip -br -4 address
ip route
ip route get 192.168.123.18
ip route get 192.168.123.161
ip route get 192.168.1.158
ip route get 1.1.1.1
```

预期关键输出：

```text
192.168.123.18 dev eth0 src 192.168.123.5
192.168.123.161 dev eth0 src 192.168.123.5
192.168.1.158 dev eth1 src 192.168.1.5
1.1.1.1 ... dev wlan0 src 192.168.0.101
```

如果 `192.168.123.161` 显示 `dev eth1`，立即停止后续步骤，修复 `eth1` 上错误的
`192.168.123.0/24` 地址或连接配置。

## 4.4 内载持久化配置

`[内载]`

先检查真实接口：

```bash
ip -br link
ip -br -4 address
nmcli -f NAME,UUID,TYPE,DEVICE connection show
```

推荐连接名 `go2-internal`：

```bash
sudo nmcli connection add \
  type ethernet ifname eth0 con-name go2-internal \
  ipv4.method manual ipv4.addresses 192.168.123.18/24 \
  ipv4.never-default yes ipv6.method disabled
```

如果已存在，则修改：

```bash
sudo nmcli connection modify go2-internal \
  connection.interface-name eth0 \
  ipv4.method manual \
  ipv4.addresses 192.168.123.18/24 \
  ipv4.gateway "" \
  ipv4.never-default yes \
  ipv6.method disabled
```

激活并检查：

```bash
sudo nmcli connection up go2-internal
ip -br -4 address show dev eth0
ip route get 192.168.123.5
ip route get 192.168.123.161
```

预期：

```text
192.168.123.5 dev eth0 src 192.168.123.18
192.168.123.161 dev eth0 src 192.168.123.18
```

## 4.5 基础连通

`[外载]`

```bash
ping -I eth0 -c 3 192.168.123.18
ping -I eth1 -c 3 192.168.1.158
```

`[内载]`

```bash
ping -I eth0 -c 3 192.168.123.5
ping -I eth0 -c 3 192.168.123.161
```

外载不必直接控制下位机，但仍应验证路由：

```bash
ip route get 192.168.123.161
```

## 4.6 Unitree DDS 网卡

`[内载]`

检查 Unitree 配置：

```bash
grep -nE 'NetworkInterface|eth[0-9]|CYCLONEDDS_URI' \
  /home/unitree/unitree_ros2/setup.sh 2>/dev/null || true
```

如果实际 Unitree 工作空间在其他位置：

```bash
find /home/unitree -maxdepth 3 -name setup.sh -path '*unitree_ros2*' -print
```

DDS 网卡必须是 `eth0`。

外载完整导航工作空间中已有：

```text
/home/nvidia/unitree_ros2/setup.sh
```

该文件此前已改为 `eth0`。重新部署后仍要检查：

```bash
grep -nE 'NetworkInterface|eth[0-9]|CYCLONEDDS_URI' \
  /home/nvidia/unitree_ros2/setup.sh
```

## 5. 阶段 C：获取代码和安装

## 5.1 外载代码

### 已有工作空间更新

`[外载]`

```bash
cd /home/nvidia/Go2_Nav_ws/src/Go2_control_gateway
git status -sb
git remote -v
git pull --ff-only
```

如果该目录不是独立 Git 仓库，不要直接执行 `git pull`；应从完整工作空间的既有部署分支更新，
或把独立仓库克隆到临时位置后有选择地同步。

### 从零克隆到 ROS 工作空间

```bash
cd /home/nvidia/Go2_Nav_ws/src

git clone \
  https://github.com/ZhenqinHuang/go2-integrated-web-console.git \
  Go2_control_gateway
```

检查 ROS 包：

```bash
test -f /home/nvidia/Go2_Nav_ws/src/Go2_control_gateway/package.xml
test -f /home/nvidia/Go2_Nav_ws/src/Go2_control_gateway/setup.py
```

## 5.2 外载依赖

```bash
sudo apt update
sudo apt install -y \
  git \
  curl \
  jq \
  rsync \
  tcpdump \
  python3-aiohttp \
  python3-pytest \
  ros-foxy-rosbridge-server
```

检查 ROS：

```bash
source /opt/ros/foxy/setup.bash
ros2 --help >/dev/null
```

检查 Unitree 消息工作空间：

```bash
test -f /home/nvidia/unitree_ros2/install/setup.bash
```

## 5.3 外载测试与构建

`[外载]`

```bash
cd /home/nvidia/Go2_Nav_ws/src/Go2_control_gateway
python3 -m pytest -q
```

如果外载已经安装 Node.js：

```bash
cd /home/nvidia/Go2_Nav_ws/src/Go2_control_gateway
bash scripts/build_frontend.sh
```

如果外载没有 Node.js，但仓库已包含经过验证的 `go2_control_gateway/web` 生产 bundle：

```bash
test -f go2_control_gateway/web/index.html
find go2_control_gateway/web/assets -maxdepth 1 -name '*.js' -print
```

构建 ROS 包：

```bash
cd /home/nvidia/Go2_Nav_ws

source /opt/ros/foxy/setup.bash
source /home/nvidia/unitree_ros2/install/setup.bash

colcon build --packages-select go2_control_gateway
source install/setup.bash

ros2 pkg prefix go2_control_gateway
ros2 pkg executables go2_control_gateway
```

预期至少看到：

```text
go2_control_gateway go2_cmd_vel_udp_sender
go2_control_gateway go2_console
go2_control_gateway go2_set_console_password
```

## 5.4 安装外载 Web 服务

有 Node.js：

```bash
cd /home/nvidia/Go2_Nav_ws
bash src/Go2_control_gateway/scripts/install_external_services.sh
```

无 Node.js，使用仓库内预构建 bundle：

```bash
cd /home/nvidia/Go2_Nav_ws

GO2_SKIP_FRONTEND_BUILD=1 \
  bash src/Go2_control_gateway/scripts/install_external_services.sh
```

首次安装时脚本会要求设置 Web `operator` 密码，并只保存 scrypt 哈希：

```text
/etc/go2-console/password.hash
```

检查权限：

```bash
sudo stat -c '%a %U %G %n' /etc/go2-console/password.hash
```

预期：

```text
600 nvidia nvidia /etc/go2-console/password.hash
```

检查服务：

```bash
systemctl is-active go2-console.service
systemctl is-active go2-console-rosbridge.service

systemctl --no-pager --full status go2-console.service
systemctl --no-pager --full status go2-console-rosbridge.service

ss -lntp | grep -E ':8080|:9090'
```

预期：

```text
192.168.0.101:8080
127.0.0.1:9090
```

如果看到 `0.0.0.0:9090`，停止验收并修复 rosbridge service。

## 5.5 内载代码

`[内载]`

推荐目录：

```bash
cd /home/unitree

git clone \
  https://github.com/ZhenqinHuang/go2-integrated-web-console.git \
  go2-integrated-web-console

cd /home/unitree/go2-integrated-web-console
```

如果通过外载复制：

`[外载]`

```bash
rsync -av --delete \
  /home/nvidia/Go2_Nav_ws/src/Go2_control_gateway/ \
  unitree@192.168.123.18:/home/unitree/go2-integrated-web-console/
```

`--delete` 只允许用于明确的目标目录
`/home/unitree/go2-integrated-web-console/`。执行前先在内载确认该目录不包含其他用户数据。

## 5.6 内载 SDK 检查

`[内载]`

先安装基础构建工具：

```bash
sudo apt update
sudo apt install -y git cmake build-essential python3
```

再检查 Unitree SDK：

```bash
test -f /usr/local/include/unitree/robot/go2/sport/sport_client.hpp
find /usr/local/lib -maxdepth 1 -name '*unitree*go2*sdk*' -print
ldconfig -p | grep -i unitree || true
```

当前 CMake 查找：

```text
/usr/local/include/unitree/robot/go2/sport/sport_client.hpp
/usr/local/lib/libunitree_go2_sdk.*
```

如果头文件或库不在该位置：

1. 先查官方 SDK 实际安装位置；
2. 修改 CMake 的查找路径或正确安装 SDK；
3. 不要创建指向未知版本库的随意软链接。

## 5.7 内载 dry-run 构建

dry-run 不连接 Unitree SDK，不会驱动机器人：

```bash
cd /home/unitree/go2-integrated-web-console

cmake -S internal_gateway \
  -B /tmp/go2_gateway_dry_build \
  -DGO2_GATEWAY_BUILD_SDK=OFF \
  -DCMAKE_BUILD_TYPE=Release

cmake --build /tmp/go2_gateway_dry_build -j2
ctest --test-dir /tmp/go2_gateway_dry_build --output-on-failure
```

手动启动 dry-run：

```bash
/tmp/go2_gateway_dry_build/go2_cmd_gateway \
  --dry-run \
  --bind 192.168.123.18 \
  --port 15000 \
  --allowed-ip 192.168.123.5 \
  --interface eth0
```

预期：

```text
READY bind=192.168.123.18:15000 allowed=192.168.123.5 interface=eth0 mode=dry-run
```

停止：

```text
Ctrl+C
```

## 5.8 内载 SDK 构建和部署

该步骤会安装真正调用 Unitree `SportClient` 的二进制。机器人仍在充电时可以构建和安装，
但不得 Arm。

```bash
cd /home/unitree/go2-integrated-web-console
bash scripts/deploy_internal_gateway.sh
```

脚本执行：

1. `GO2_GATEWAY_BUILD_SDK=ON`；
2. 构建 `go2_cmd_gateway`；
3. 停止旧服务；
4. 安装 `/usr/local/bin/go2_cmd_gateway`；
5. 安装 `/etc/go2-cmd-gateway/gateway.env`；
6. 安装 systemd unit；
7. enable 并启动服务。

验证二进制：

```bash
file /usr/local/bin/go2_cmd_gateway
ldd /usr/local/bin/go2_cmd_gateway
```

`ldd` 不得包含：

```text
not found
```

验证配置：

```bash
sudo cat /etc/go2-cmd-gateway/gateway.env
```

预期：

```text
GO2_GATEWAY_BIND_IP=192.168.123.18
GO2_GATEWAY_PORT=15000
GO2_GATEWAY_ALLOWED_IP=192.168.123.5
GO2_GATEWAY_INTERFACE=eth0
```

检查服务：

```bash
systemctl is-enabled go2-cmd-gateway.service
systemctl is-active go2-cmd-gateway.service
systemctl --no-pager --full status go2-cmd-gateway.service
journalctl -u go2-cmd-gateway.service -n 100 --no-pager
ss -lunp | grep 15000
```

预期：

```text
READY bind=192.168.123.18:15000 allowed=192.168.123.5 interface=eth0 mode=unitree
```

服务启动时构造函数立即调用 `StopMove()`，初始状态为 `LOCKED`。

## 6. 阶段 D：无运动链路检查

本阶段不 Arm。

## 6.1 确认只有一个执行路径

`[外载]`

```bash
pgrep -af 'go2_cmd_vel_udp_sender|go2_cmd_vel_bridge_node'
```

正常 UDP 路径：

```text
存在 go2_cmd_vel_udp_sender
不存在 go2_cmd_vel_bridge_node
```

如果两者同时存在：

```bash
cd /home/nvidia/Go2_Nav_ws
bash src/Go2_bringup/go2_gateway_disarm.sh || true
pkill -f go2_cmd_vel_bridge_node
pkill -f go2_cmd_vel_udp_sender
```

然后只启动 UDP sender。

## 6.2 单独启动 UDP sender

`[外载]`

```bash
cd /home/nvidia/Go2_Nav_ws

source /opt/ros/foxy/setup.bash
source /home/nvidia/unitree_ros2/install/setup.bash
source install/setup.bash

ros2 launch go2_control_gateway udp_sender.launch.py
```

预期：

```text
UDP sender ready: 192.168.123.5:15001 -> 192.168.123.18:15000 at 20.0 Hz
```

另开终端：

```bash
ss -lunp | grep 15001
ros2 node list | grep go2_cmd_vel_udp_sender
ros2 service list | grep /go2_cmd_vel_gateway/arm
```

## 6.3 检查 ACK 与 LOCKED

`[外载]`

```bash
source /opt/ros/foxy/setup.bash
source /home/nvidia/Go2_Nav_ws/install/setup.bash

ros2 topic echo \
  /go2_cmd_vel_gateway/status \
  std_msgs/msg/String \
  --once
```

预期 JSON：

```json
{
  "gateway_link": "online",
  "armed": false,
  "nav_active": false,
  "last_ack_age_sec": 0.05,
  "send_hz": 20.0
}
```

判定：

- `gateway_link=online`：外载控制帧到达内载，ACK 返回外载；
- `armed=false`：当前仍为 LOCKED；
- 这一阶段不会调用 `BalanceStand` 或 `Move`。

如果 offline，转到第 11.2 节。

## 6.4 抓包确认数据流

`[外载]`

```bash
sudo tcpdump -ni eth0 \
  'udp and (port 15000 or port 15001)'
```

预期每 50 ms 左右看到：

```text
192.168.123.5.15001 > 192.168.123.18.15000
192.168.123.18.15000 > 192.168.123.5.15001
```

停止：

```text
Ctrl+C
```

不要把包含现场敏感信息的大量抓包上传到公开仓库。

## 7. 阶段 E：启动传感器、定位和 Nav2

本项目保留既有 MID360、建图、定位和 Nav2 流程。具体雷达/定位命令以
`Go2_Nav_ws/src/Go2_bringup` 的现有脚本为准。

### 7.1 最低前置 ROS 数据

```bash
ros2 topic list | grep -E '^/scan$|^/map_to_odom$|^/odom$'

ros2 topic hz /scan
ros2 topic hz /map_to_odom
ros2 topic echo /map_to_odom --once
```

sender 的定位保护默认开启。没有新鲜 `/map_to_odom` 时，即使 ARMED，也只发送零速度。

### 7.2 启动 Nav2 和 UDP sender

`[外载]`

```bash
cd /home/nvidia/Go2_Nav_ws

GO2_CONTROL_BACKEND=udp \
MAP_YAML=/home/nvidia/Go2_Nav_ws/maps/MID360_map.yaml \
USE_RVIZ=false \
bash src/Go2_bringup/run_nav2.sh
```

脚本默认：

```text
GO2_CONTROL_BACKEND=udp
```

它会先启动：

```bash
ros2 launch go2_control_gateway udp_sender.launch.py
```

再启动：

```bash
ros2 launch go2_nav2 nav2_bringup.launch.py
```

sender 日志：

```bash
tail -f /tmp/go2_cmd_vel_gateway.log
```

### 7.3 Nav2 检查

```bash
ros2 node list | sort
ros2 topic info /cmd_vel -v
ros2 action list | grep -E 'navigate_to_pose|follow_waypoints|navigate_through_poses'
ros2 lifecycle nodes
```

在没有导航目标时 `/cmd_vel` 可能没有持续输出，这是正常现象。

## 8. 阶段 F：Web 控制台

## 8.1 访问

局域网浏览器：

```text
http://192.168.0.101:8080
```

登录凭据从受控飞书文档读取，不写入 GitHub。

### 8.2 正确的页面状态

登录后首先检查：

| 项目 | 允许继续的状态 |
|---|---|
| 网关 | `online` |
| Arm | 关闭 |
| 控制权 | 未占用或可接管 |
| Nav2 | `IDLE`，手动测试时必须如此 |
| 当前速度 | 0 |
| 里程计 | 有效并随机器人状态更新 |
| 电量 | 可读；缺失时检查 `/lowstate` |
| 运动模式 | 可读；缺失时检查 `/sportmodestate` |

### 8.3 Web 正常操作顺序

1. 登录；
2. 检查状态；
3. 点击“接管控制”；
4. 现场确认安全；
5. 点击 Arm；
6. 等待网关显示 ARMED；
7. 导航：在地图发送目标；
8. 手动：先取消导航并等待 IDLE；
9. 按住方向按钮才运动；
10. 松开按钮立即停车；
11. 结束后点击 Disarm；
12. 确认 Arm 关闭、速度为 0。

### 8.4 页面手动速度

- 默认前进速度：`0.25 m/s`；
- 默认转向速度：`0.6 rad/s`；
- 可调前进范围：`0.05～0.6 m/s`；
- 可调转向范围：`0.1～1.4 rad/s`；
- 页面侧移按钮虽然存在，但后端和内载都会把 `vy` 限制为 0；
- 页面滑块只影响手动速度，不修改 Nav2 参数。

首次实机验收应把前进滑块调到 `0.10 m/s`。

### 8.5 Web 失联行为

以下事件触发归零：

- 松开按钮；
- 指针离开按钮；
- `pointercancel`；
- 键盘按键释放；
- 浏览器窗口失焦；
- 页面隐藏；
- `/ws/state` 断开；
- 控制租约超过 2 秒无 heartbeat；
- 手动命令超过 0.2 秒；
- Nav2 变为活跃；
- 网关 ACK 失联；
- 内载控制帧失联。

## 9. 调用接口

## 9.1 ROS CLI：查看网关状态

`[外载]`

```bash
cd /home/nvidia/Go2_Nav_ws
bash src/Go2_bringup/go2_gateway_status.sh
```

或：

```bash
source /opt/ros/foxy/setup.bash
source /home/nvidia/Go2_Nav_ws/install/setup.bash

ros2 topic echo \
  /go2_cmd_vel_gateway/status \
  std_msgs/msg/String \
  --once
```

## 9.2 ROS CLI：Arm

> 这一步会调用内载 `BalanceStand()`。只有机器人离开充电器、四脚着地、现场安全时才能执行。

```bash
cd /home/nvidia/Go2_Nav_ws
bash src/Go2_bringup/go2_gateway_arm.sh
```

或：

```bash
ros2 service call \
  /go2_cmd_vel_gateway/arm \
  std_srvs/srv/SetBool \
  "{data: true}"
```

预期：

```text
success: true
message: ARMED
```

如果 1 秒内没有进入 ARMED，sender 会发送 Disarm 并撤销该 token。

## 9.3 ROS CLI：Disarm

```bash
cd /home/nvidia/Go2_Nav_ws
bash src/Go2_bringup/go2_gateway_disarm.sh
```

或：

```bash
ros2 service call \
  /go2_cmd_vel_gateway/arm \
  std_srvs/srv/SetBool \
  "{data: false}"
```

## 9.4 ROS CLI：低速手动命令

> 仅在第 10 节所有安全前提满足后执行。必须先有新鲜 `/map_to_odom`，Nav2 必须 IDLE。

终端 A 准备随时 Disarm：

```bash
cd /home/nvidia/Go2_Nav_ws
bash src/Go2_bringup/go2_gateway_disarm.sh
```

终端 B Arm：

```bash
cd /home/nvidia/Go2_Nav_ws
bash src/Go2_bringup/go2_gateway_arm.sh
```

终端 B 以 `0.1 m/s` 持续 4 秒，理论距离约 0.4 米：

```bash
timeout 4s ros2 topic pub -r 10 \
  /go2/manual_cmd_vel \
  geometry_msgs/msg/Twist \
  "{linear: {x: 0.1, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}"
```

命令结束后立即显式归零：

```bash
ros2 topic pub --once \
  /go2/manual_cmd_vel \
  geometry_msgs/msg/Twist \
  "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}"
```

然后 Disarm：

```bash
cd /home/nvidia/Go2_Nav_ws
bash src/Go2_bringup/go2_gateway_disarm.sh
```

即使 `timeout` 或终端异常，0.2 秒手动命令超时和内载 0.5 秒 watchdog 仍会触发停车；
但不能用 watchdog 替代正常显式归零和 Disarm。

## 9.5 ROS CLI：单点 Nav2 目标

```bash
ros2 action send_goal \
  /navigate_to_pose \
  nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: 1.0, y: 0.5, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0}}}}"
```

Nav2 生成的 `/cmd_vel` 会进入 UDP sender。

取消：

```bash
ros2 service call \
  /navigate_to_pose/_action/cancel_goal \
  action_msgs/srv/CancelGoal \
  "{goal_info: {goal_id: {uuid: [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]}, stamp: {sec: 0, nanosec: 0}}}"
```

更推荐使用 RViz 或 Web 的“取消导航”按钮。

## 9.6 Web HTTP API：只读检查

以下示例不把密码写入 shell 历史：

```bash
read -r -s -p "Web operator password: " GO2_WEB_PASSWORD
echo

COOKIE_JAR="$(mktemp)"

LOGIN_JSON="$(
  jq -n \
    --arg username operator \
    --arg password "${GO2_WEB_PASSWORD}" \
    '{username:$username,password:$password}' |
  curl -sS \
    -c "${COOKIE_JAR}" \
    -H 'Content-Type: application/json' \
    --data-binary @- \
    http://192.168.0.101:8080/api/login
)"

unset GO2_WEB_PASSWORD

CSRF_TOKEN="$(printf '%s' "${LOGIN_JSON}" | jq -r '.csrf_token')"

curl -sS \
  -b "${COOKIE_JAR}" \
  http://192.168.0.101:8080/api/state |
jq
```

清理：

```bash
rm -f -- "${COOKIE_JAR}"
unset COOKIE_JAR LOGIN_JSON CSRF_TOKEN
```

### HTTP 改变状态请求的形式

```bash
curl -sS \
  -b "${COOKIE_JAR}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H 'Content-Type: application/json' \
  -X POST \
  http://192.168.0.101:8080/api/control/acquire
```

不建议用一组独立 curl 命令做持续手动控制，因为控制租约要求 `/ws/state` 每 0.5 秒发送
heartbeat。正式操作使用 Web 页面；程序化客户端必须完整实现：

1. 登录 Cookie；
2. CSRF；
3. `/ws/state`；
4. heartbeat；
5. 控制权；
6. Arm；
7. 手动命令刷新；
8. 零速度；
9. Disarm；
10. 断连处理。

## 9.7 WebSocket ROS 可视化接口

浏览器连接：

```text
ws://192.168.0.101:8080/ws/ros
```

允许示例：

```json
{
  "op": "subscribe",
  "id": "map-subscription",
  "topic": "/map",
  "type": "nav_msgs/msg/OccupancyGrid",
  "throttle_rate": 250,
  "queue_length": 1
}
```

拒绝示例：

```json
{
  "op": "publish",
  "topic": "/cmd_vel",
  "msg": {}
}
```

后端会返回 error status，不会转发给 rosbridge。

## 10. 分级验收

## 10.1 一级：无运动验收

- [ ] 外载 `wlan0=192.168.0.101`；
- [ ] 外载 `eth0=192.168.123.5`；
- [ ] 外载 `eth1=192.168.1.5`；
- [ ] 内载 `eth0=192.168.123.18`；
- [ ] `192.168.123.18` 和 `.161` 路由走外载 `eth0`；
- [ ] `192.168.1.158` 路由走 `eth1`；
- [ ] 内载能 ping `192.168.123.161`；
- [ ] 内载 SDK 二进制 `ldd` 无缺失；
- [ ] 内载监听 UDP 15000；
- [ ] 外载监听 UDP 15001；
- [ ] sender 状态 `gateway_link=online`；
- [ ] sender 状态 `armed=false`；
- [ ] Web 页面能登录；
- [ ] `9090` 仅监听 `127.0.0.1`；
- [ ] 浏览器 publish `/cmd_vel` 被拒绝；
- [ ] 没有同时运行旧 DDS bridge。

本级通过前不得进入二级。

## 10.2 二级：Arm/Disarm 验收

现场条件：

- [ ] 已离开充电器；
- [ ] 四脚着地；
- [ ] 周边安全；
- [ ] 操作员准备好 Disarm。

执行：

1. Web 接管控制；
2. 点击 Arm；
3. 观察 `ARMING`；
4. 约 0.8 秒后进入 `ARMED`；
5. 不发送非零速度；
6. 点击 Disarm；
7. 确认 `LOCKED`。

记录内载日志：

```bash
journalctl -u go2-cmd-gateway.service -f
```

判定：

- `BalanceStand()` 返回 0；
- Arm 未自动重复；
- Disarm 调用 `StopMove()`；
- Disarm 后旧 token 无法恢复。

## 10.3 三级：低速 0.4 米

1. 手动速度设为 `0.10 m/s`；
2. Arm；
3. 按住前进约 4 秒；
4. 松开；
5. 确认约 0.4 米且立即停止；
6. Disarm；
7. 确认 LOCKED。

判定：

- [ ] Go2 真实迈步，不只是身体前探；
- [ ] 方向正确；
- [ ] 松开后立即停止；
- [ ] 页面显示速度回零；
- [ ] `vy` 始终为 0；
- [ ] Disarm 后按钮不可运动。

如果只前探不迈步：

1. 立即 Disarm；
2. 查看 `SportClient.Move` 返回码；
3. 检查是否完成 `BalanceStand` 和 0.8 秒 ARMING；
4. 检查内载是否使用官方 SDK 和 `eth0`；
5. 不要连续加大速度试错。

## 10.4 四级：watchdog 拔线

仅在空旷、安全、低速条件下：

1. Arm；
2. 以 `0.1 m/s` 低速运动；
3. 断开外载到内载控制链路；
4. 计时；
5. Go2 应在 0.5 秒内 `StopMove` 并 LOCKED；
6. 恢复网线；
7. 确认不会自动继续运动；
8. 必须重新 Arm。

## 10.5 五级：Nav2 全链路

1. 确认定位稳定；
2. 启动 Nav2，`GO2_CONTROL_BACKEND=udp`；
3. Web 接管并 Arm；
4. 发送近距离目标；
5. 观察 `/cmd_vel`；
6. 观察 `/go2_cmd_vel_gateway/status`；
7. 确认 Go2 按规划运动；
8. Nav2 活跃时尝试手动按钮，应保持禁用；
9. 人工取消导航；
10. 等待 `IDLE`；
11. Disarm。

监视命令：

```bash
ros2 topic echo /cmd_vel
ros2 topic echo /go2_cmd_vel_gateway/status
ros2 topic echo /navigate_to_pose/_action/status
```

## 11. 故障排查

## 11.1 快速总览

`[外载]`

```bash
date
hostname
ip -br -4 address
ip route
ip route get 192.168.123.18
ip route get 192.168.123.161
ip route get 192.168.1.158
ping -I eth0 -c 3 192.168.123.18
ping -I eth1 -c 3 192.168.1.158
ss -lntup | grep -E ':8080|:9090|:15000|:15001'
pgrep -af 'go2_cmd_vel_udp_sender|go2_cmd_vel_bridge_node'
ros2 node list
ros2 topic list
```

`[内载]`

```bash
date
hostname
ip -br -4 address
ip route get 192.168.123.5
ip route get 192.168.123.161
ping -I eth0 -c 3 192.168.123.5
ping -I eth0 -c 3 192.168.123.161
systemctl status go2-cmd-gateway.service
ss -lunp | grep 15000
journalctl -u go2-cmd-gateway.service -n 100 --no-pager
```

## 11.2 `gateway_link=offline`

按顺序：

1. 外载是否有 `eth0` 载波；
2. `eth0` 是否为 `192.168.123.5`；
3. 路由是否走 `eth0`；
4. 能否 ping `192.168.123.18`；
5. sender 是否监听 `15001`；
6. 内载是否监听 `15000`；
7. 内载 `allowed-ip` 是否为 `192.168.123.5`；
8. tcpdump 是否看到控制帧；
9. tcpdump 是否看到 ACK；
10. ACK 是否来自 `192.168.123.18:15000`。

外载：

```bash
ip route get 192.168.123.18
ping -I eth0 -c 3 192.168.123.18
ss -lunp | grep 15001
sudo tcpdump -ni eth0 'udp port 15000 or udp port 15001'
```

内载：

```bash
ss -lunp | grep 15000
sudo cat /etc/go2-cmd-gateway/gateway.env
journalctl -u go2-cmd-gateway.service -n 100 --no-pager
```

## 11.3 可以 ping 内载，但没有 ACK

可能原因：

- 内载服务未运行；
- bind IP 不是 `192.168.123.18`；
- allowed IP 不匹配；
- 外载源地址不是 `192.168.123.5`；
- 防火墙拦截 UDP；
- 协议版本或 CRC 不匹配。

检查防火墙：

```bash
sudo ufw status verbose
sudo nft list ruleset
```

不要直接永久关闭防火墙。先确认规则，再只放行两板固定地址的 UDP 15000/15001。

## 11.4 Arm 失败

外载：

```bash
ros2 topic echo /go2_cmd_vel_gateway/status --once
ros2 service call \
  /go2_cmd_vel_gateway/arm \
  std_srvs/srv/SetBool \
  "{data: true}"
```

内载：

```bash
journalctl -u go2-cmd-gateway.service -f
```

检查：

- link 是否 online；
- ACK 是否在 0.5 秒内；
- `BalanceStand()` 返回码是否为 0；
- Arm token 是否新生成；
- ARMING 期间是否持续 20 Hz；
- sender 是否在 1 秒内确认 ARMED；
- 是否有另一个 sender 会话切换。

## 11.5 ARMED 但不运动

按顺序检查：

```bash
ros2 topic hz /map_to_odom
ros2 topic echo /map_to_odom --once
ros2 topic echo /navigate_to_pose/_action/status --once
ros2 topic echo /go2/manual_cmd_vel
ros2 topic echo /cmd_vel
ros2 topic echo /go2_cmd_vel_gateway/status
```

常见原因：

- 定位保护没有收到 `/map_to_odom`；
- Nav2 状态仍活跃，手动命令被拒绝；
- 手动发布频率低于 5 Hz，0.2 秒超时；
- Nav2 `/cmd_vel` 超过 0.6 秒没有更新；
- 速度在 0.03 死区内；
- `vy` 被强制为 0；
- 内载 `Move()` 返回非零；
- Go2 没有完成 BalanceStand；
- DDS 网卡不是内载 `eth0`。

## 11.6 下位机 `192.168.123.161` 不通

`[内载]`

```bash
ip route get 192.168.123.161
ping -I eth0 -c 3 192.168.123.161
ip neigh show dev eth0
```

如果 ping 通但 SportClient 失败：

- 检查 `ChannelFactory::Init(0, "eth0")`；
- 检查 Unitree SDK 版本；
- 检查 DDS domain/config；
- 检查下位机运动服务是否可用；
- 查看 SDK 返回码；
- 不要把接口改成 `eth1`。

## 11.7 Web 打不开

`[外载]`

```bash
systemctl status go2-console.service
journalctl -u go2-console.service -n 100 --no-pager
ss -lntp | grep 8080
curl -I http://192.168.0.101:8080/
```

检查 `wlan0` 是否仍为 `192.168.0.101`。

## 11.8 Web 可打开但没有地图

```bash
systemctl status go2-console-rosbridge.service
journalctl -u go2-console-rosbridge.service -n 100 --no-pager
ss -lntp | grep 9090
ros2 topic list | grep -E '/map|/scan|/tf|/plan|/odom'
```

`9090` 必须是 `127.0.0.1:9090`。

## 11.9 HTTP 状态码

| 状态码 | 常见原因 |
|---:|---|
| 400 | JSON、位姿、waypoint 数量或数值错误 |
| 401 | 未登录或会话过期 |
| 403 | CSRF 或跨域 WebSocket 被拒绝 |
| 409 | 控制权被其他会话占用，或 Nav2/手动互锁 |
| 429 | API 速率限制 |
| 503 | ROS service/action、Arm 或底层接口失败 |

## 11.10 雷达异常

```bash
ip route get 192.168.1.158
ping -I eth1 -c 3 192.168.1.158
ros2 topic hz /livox/lidar
ros2 topic hz /livox/imu
```

雷达故障只在 `eth1` 排查，不要把 `192.168.123.0/24` 地址加到 `eth1`。

## 12. 正常停机与恢复

### 12.1 正常停机

`[外载]`

```bash
cd /home/nvidia/Go2_Nav_ws
bash src/Go2_bringup/go2_gateway_disarm.sh
```

确认：

```bash
bash src/Go2_bringup/go2_gateway_status.sh
```

然后：

```bash
sudo systemctl stop go2-console.service
sudo systemctl stop go2-console-rosbridge.service
```

`[内载]`

```bash
sudo systemctl stop go2-cmd-gateway.service
```

### 12.2 失联恢复

1. 不发送旧目标；
2. 检查机器人姿态和现场；
3. 检查网线和 `eth0`；
4. 检查两端路由；
5. 检查内载服务；
6. 检查 sender ACK；
7. 取消残留 Nav2 目标；
8. 确认状态 LOCKED；
9. 重新接管控制；
10. 使用新 token 重新 Arm。

## 13. 诊断回退

旧外载直连 DDS 只用于定位问题。

切换前：

```bash
cd /home/nvidia/Go2_Nav_ws
bash src/Go2_bringup/go2_gateway_disarm.sh
pkill -f go2_cmd_vel_udp_sender || true
```

启动旧路径：

```bash
GO2_CONTROL_BACKEND=direct-dds \
MAP_YAML=/home/nvidia/Go2_Nav_ws/maps/MID360_map.yaml \
bash src/Go2_bringup/run_nav2.sh
```

回到正常路径：

```bash
pkill -f go2_cmd_vel_bridge_node || true

GO2_CONTROL_BACKEND=udp \
MAP_YAML=/home/nvidia/Go2_Nav_ws/maps/MID360_map.yaml \
bash src/Go2_bringup/run_nav2.sh
```

任何切换前后都要 Disarm。不得同时运行两个执行器。

## 14. 开发与测试命令

## 14.1 Python

```bash
cd /path/to/go2-integrated-web-console
python3 -m pytest -q
```

## 14.2 前端

```bash
cd /path/to/go2-integrated-web-console/frontend
npm ci
npm test -- --run
npm run lint
npm run build
npm audit --omit=dev
```

说明：

- `npm audit --omit=dev` 检查生产依赖；
- 完整 `npm ci` 在 2026-07-29 曾报告 5 个开发依赖高危项；
- 不得把“生产依赖无漏洞”和“完整开发依赖无漏洞”混为一谈；
- 升级构建依赖前应重新运行前端测试和真实浏览器验收。

## 14.3 内载 C++ 无 SDK 测试

```bash
cmake -S internal_gateway \
  -B /tmp/go2_gateway_build \
  -DGO2_GATEWAY_BUILD_SDK=OFF

cmake --build /tmp/go2_gateway_build -j2
ctest --test-dir /tmp/go2_gateway_build --output-on-failure
```

## 14.4 内载 C++ SDK 构建

```bash
cmake -S internal_gateway \
  -B /tmp/go2_gateway_sdk_build \
  -DGO2_GATEWAY_BUILD_SDK=ON \
  -DCMAKE_BUILD_TYPE=Release

cmake --build /tmp/go2_gateway_sdk_build -j2
ldd /tmp/go2_gateway_sdk_build/go2_cmd_gateway
```

## 15. 变更代码定位

核心调用链：

```text
Nav2 /cmd_vel
  → go2_control_gateway/udp_sender_node.py
  → go2_control_gateway/sender_core.py
  → go2_control_gateway/protocol.py
  → UDP
  → internal_gateway/src/main.cpp
  → internal_gateway/src/gateway_core.cpp
  → internal_gateway/src/unitree_sport_api.cpp
  → SportClient.Move()
```

Web 手动链：

```text
frontend/src/components/Go2ControlPanel.tsx
  → frontend/src/api/consoleClient.ts
  → go2_control_gateway/console_server.py
  → go2_control_gateway/console_core.py
  → go2_control_gateway/ros_adapter.py
  → /go2/manual_cmd_vel
  → udp_sender_node.py
```

Web 导航目标：

```text
frontend Navigation UI
  → /api/navigation/goal 或 /api/navigation/waypoints
  → console_server.py
  → ros_adapter.py
  → /navigate_to_pose
  → Nav2
  → /cmd_vel
```

查看相对原工程的完整新增文件：

```bash
git diff --name-status <引入网关前的提交> HEAD -- \
  'src/Go2_control_gateway/**' \
  'src/Go2_bringup/go2_gateway*' \
  'docs/go2-*'
```

独立仓库的主要文件职责见配套
[架构与接口说明第 16 节](Jetson_NX到Go2_控制链路架构与接口.md#16-新增代码与文件)。

## 16. 验收记录模板

### 16.1 环境

```text
日期：
操作员：
外载 hostname：
外载系统/ROS：
外载 Git commit：
内载 hostname：
内载系统：
内载 Git commit：
Unitree SDK 版本：
Go2 固件版本：
地图文件：
```

获取版本：

```bash
git rev-parse HEAD
uname -a
lsb_release -a
printenv ROS_DISTRO
```

### 16.2 网络

| 检查项 | 结果 | 实际输出/备注 |
|---|---|---|
| 外载 wlan0 `192.168.0.101` |  |  |
| 外载 eth0 `192.168.123.5` |  |  |
| 外载 eth1 `192.168.1.5` |  |  |
| 内载 eth0 `192.168.123.18` |  |  |
| `.18` 经外载 eth0 |  |  |
| `.161` 经外载 eth0 |  |  |
| MID360 经 eth1 |  |  |

### 16.3 服务与链路

| 检查项 | 结果 | 时间/备注 |
|---|---|---|
| 内载 SDK 构建 |  |  |
| 内载服务 active |  |  |
| 内载 UDP 15000 |  |  |
| 外载 sender UDP 15001 |  |  |
| ACK online |  |  |
| 初始 LOCKED |  |  |
| Web 登录 |  |  |
| rosbridge 仅回环 |  |  |

### 16.4 实机

| 检查项 | 结果 | 时间/备注 |
|---|---|---|
| BalanceStand |  |  |
| 0.8 秒 ARMING |  |  |
| ARMED |  |  |
| Disarm/LOCKED |  |  |
| 0.1 m/s、约 0.4 m |  |  |
| 松开立即停车 |  |  |
| 0.5 秒拔线保护 |  |  |
| Nav2/手动互锁 |  |  |
| Nav2 全链路 |  |  |

## 17. 已有历史记录

### 2026-07-28

- 外载 Web 源码部署到 `/home/nvidia/Go2_Nav_ws/src/Go2_control_gateway`；
- 外载 `go2-console.service` 与回环 rosbridge 曾确认 active；
- 控制台首页、登录、状态 API 曾返回 HTTP 200；
- rosbridge 直接 publish `/cmd_vel` 被拒绝；
- 内载/Go2 关机时页面显示 gateway offline、armed false；
- 外载和本地 Python/前端测试通过；
- 新 UDP 网关完成协议、状态机和 dry-run 验证；
- 旧 Unitree 直连路径曾确认 Go2 可以迈步。

### 2026-07-29

- 生成本架构说明和联调 Runbook；
- 本地独立仓库基线：Python 103 通过、3 项因缺少相邻 `Go2_bringup` 跳过；
- 前端基线：23 项通过；
- 完整开发依赖审计出现 5 个高危项，需与生产依赖审计区分；
- 开发电脑重新连接 `192.168.0.101` 时 SSH/ICMP 超时，现场实时状态待重新核验；
- 内载 SDK 实机部署、0.5 秒实机 watchdog、0.4 米低速和 Nav2 新链路仍须按本 Runbook 验收。

## 18. 最短打通路径

如果代码已经安装，只按以下顺序：

1. `[外载]` 检查 `.18/.161 → eth0`、雷达 → `eth1`；
2. `[内载]` 检查 `.161 → eth0`；
3. `[内载]` 启动 `go2-cmd-gateway.service`；
4. `[外载]` 启动 UDP sender；
5. `[外载]` 确认 `gateway_link=online, armed=false`；
6. `[外载]` 启动定位，确认 `/map_to_odom`；
7. `[外载]` 启动 Nav2，`GO2_CONTROL_BACKEND=udp`；
8. 打开 Web、登录、检查状态；
9. 机器人离开充电器并确认安全；
10. 接管控制、Arm、等待 ARMED；
11. 先做 0.1 m/s、4 秒手动测试；
12. 松开、归零、Disarm；
13. 通过后再做近距离 Nav2；
14. 任务结束 Disarm 并确认 LOCKED。
