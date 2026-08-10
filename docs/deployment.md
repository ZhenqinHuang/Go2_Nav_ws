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
