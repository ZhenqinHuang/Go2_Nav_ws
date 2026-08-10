# 部署与网络

## 固定地址

| 接口/设备 | 地址 | 路由职责 |
|---|---:|---|
| Jetson `wlan0` | `192.168.0.101/24` | SSH、Web、默认路由 |
| Jetson `eth0` | `192.168.123.5/24` | Go2 控制专网，无默认网关 |
| Jetson `eth1` | `192.168.1.5/24` | MID360S 专网，无默认网关 |
| 内载 Ubuntu | `192.168.123.18/24` | UDP 安全网关 |
| Go2 下位机 | `192.168.123.161/24` | Sport API |
| MID360S | `192.168.1.158/24` | 激光雷达 |

Unitree DDS 的网卡配置保持 `eth0`。预期路由：

```bash
ip route get 192.168.123.18
ip route get 192.168.123.161
ip route get 192.168.1.158
ip route get 1.1.1.1
```

前两项必须走 `eth0`，雷达必须走 `eth1`，互联网默认路由必须走 `wlan0`。

## 构建

目标平台是 Jetson Ubuntu/ROS 2。不要把 Windows 的缓存、构建目录或 frontend `dist` 当作源码复制。

```bash
cd /home/nvidia/Go2_Nav_ws
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

Web 前端在其包目录单独安装依赖并生成 production bundle。部署时由 `go2-console.service` 提供端口 `8080`，只读 rosbridge 绑定 `127.0.0.1:9090`。

## 服务边界

- `go2-console.service`：Web 后端和静态文件；
- `go2-console-rosbridge.service`：仅回环只读桥；
- `go2-motion-sender.service`：外载 UDP sender；
- 内载 `go2_cmd_gateway`：UDP 到 SportClient；
- PTP 服务：可选，不代替主机 NTP 时间有效性检查。

切换正式服务前，先在版本化 staging 目录构建和执行零速度 smoke test。保留当前 unit 文件和源码路径作为回滚目标。

## 已验证 staging

```text
/home/nvidia/Go2_Nav_ws_staging/go2-nav-a9e7854-20260810T1550
SHA-256: 4a7fd30ee5df4d4d5a2b128da86fae177dc50f44ac843e987ee86191e6580b70
```

该目录已经通过 [2026-08-10 验证报告](verification-report-2026-08-10.md)中的零运动检查。
带 `REJECTED-map-crlf` 后缀的旧目录不得部署。

## 正式切换命令（尚未执行）

先构建 release。目标机无 npm，但仓库已包含经过验证的 production bundle，构建脚本会检查后
跳过前端重建。

```bash
set -Eeuo pipefail
RELEASE=/home/nvidia/Go2_Nav_ws_staging/go2-nav-a9e7854-20260810T1550
STAMP="$(date +%Y%m%d_%H%M%S)"
ROLLBACK="/home/nvidia/Go2_Nav_ws_rollbacks/pre-a9e7854-${STAMP}"

cd "$RELEASE"
python3 scripts/map_bundle.py validate maps
bash scripts/install.sh

mkdir -p "$ROLLBACK/systemd" "$ROLLBACK/new-units"
sudo cp -a /etc/systemd/system/go2-console.service "$ROLLBACK/systemd/"
sudo cp -a /etc/systemd/system/go2-console-rosbridge.service "$ROLLBACK/systemd/"
sudo cp -a /etc/systemd/system/go2-motion-sender.service "$ROLLBACK/systemd/"

sudo systemctl stop go2-navigation.service go2-mapping.service 2>/dev/null || true
sudo systemctl stop go2-console.service go2-console-rosbridge.service go2-motion-sender.service

test -d /home/nvidia/Go2_Nav_ws
test ! -L /home/nvidia/Go2_Nav_ws
sudo mv /home/nvidia/Go2_Nav_ws "$ROLLBACK/workspace"
sudo ln -s "$RELEASE" /home/nvidia/Go2_Nav_ws

sudo install -m 0644 src/Go2_web_console/systemd/go2-console.service /etc/systemd/system/
sudo install -m 0644 src/Go2_web_console/systemd/go2-console-rosbridge.service /etc/systemd/system/
sudo install -m 0644 src/Go2_control_gateway/systemd/go2-motion-sender.service /etc/systemd/system/
sudo install -m 0644 src/Go2_bringup/systemd/go2-navigation.service /etc/systemd/system/
sudo install -m 0644 src/Go2_bringup/systemd/go2-mapping.service /etc/systemd/system/
sudo install -m 0644 src/Go2_time_sync/config/ptp_sync.service /etc/systemd/system/
sudo systemctl daemon-reload

sudo systemctl enable go2-console-rosbridge.service go2-console.service go2-motion-sender.service
sudo systemctl start go2-console-rosbridge.service go2-console.service go2-motion-sender.service
```

切换后不自动启动导航、建图或 PTP。先检查 Web、地图和控制状态；`eth0`、ACK、定位和急停状态
全部通过后，才允许另行启动导航。

```bash
curl -f http://192.168.0.101:8080/
bash scripts/check_system.sh --stage base
systemctl --no-pager --full status go2-console.service go2-motion-sender.service
```

## 回滚命令

以下命令假设使用上节生成的同一个 `ROLLBACK` 路径。所有新文件均移动到回滚目录，不直接
删除。

```bash
set -Eeuo pipefail
ROLLBACK=/home/nvidia/Go2_Nav_ws_rollbacks/pre-a9e7854-<切换时间戳>

sudo systemctl stop go2-navigation.service go2-mapping.service 2>/dev/null || true
sudo systemctl stop go2-console.service go2-console-rosbridge.service go2-motion-sender.service

test -L /home/nvidia/Go2_Nav_ws
sudo mv /home/nvidia/Go2_Nav_ws "$ROLLBACK/release-link"
sudo mv "$ROLLBACK/workspace" /home/nvidia/Go2_Nav_ws

sudo mv /etc/systemd/system/go2-navigation.service "$ROLLBACK/new-units/" 2>/dev/null || true
sudo mv /etc/systemd/system/go2-mapping.service "$ROLLBACK/new-units/" 2>/dev/null || true
sudo mv /etc/systemd/system/ptp_sync.service "$ROLLBACK/new-units/" 2>/dev/null || true
sudo install -m 0644 "$ROLLBACK/systemd/go2-console.service" /etc/systemd/system/
sudo install -m 0644 "$ROLLBACK/systemd/go2-console-rosbridge.service" /etc/systemd/system/
sudo install -m 0644 "$ROLLBACK/systemd/go2-motion-sender.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start go2-console-rosbridge.service go2-console.service go2-motion-sender.service
```
