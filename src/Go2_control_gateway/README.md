# Go2 Integrated Web Console

面向 Unitree Go2 的 ROS 2 导航、可视化与安全运动控制台。系统保留外载 Jetson 上已经验证的
MID360、建图、定位和 Nav2 链路，并通过 fail-closed UDP 网关把速度交给内载计算机，再由
Unitree 原生 `SportClient` 控制下位机。

Web 前端基于 [`lijinghai/ljh_robot_ros2_web`](https://github.com/lijinghai/ljh_robot_ros2_web)
融合开发，增加了与现场控制架构匹配的登录、单操作员控制权、Nav2/手动互锁、
速度调节和网关状态。第三方许可证与改动说明见
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

后端入口为 ROS 2 可执行程序 `go2_console`，速度发送节点为
`go2_cmd_vel_udp_sender`。

## 端到端文档

建议按以下顺序阅读：

1. [Jetson NX 到 Go2：外载—内载控制链路架构与接口说明](docs/Jetson_NX到Go2_控制链路架构与接口.md)：
   设备拓扑、数据流、ROS/HTTP/UDP 接口、状态机、SportClient 调用和新增代码文件。
2. [Jetson NX 到 Go2：外载—内载控制链路部署联调日志](docs/Jetson_NX到Go2_控制链路部署联调日志.md)：
   IP 配置、构建安装、启动命令、接口调用、分级验收、停机和故障排查。

## 功能

- ROS 地图、激光、TF、路径、代价地图和点云可视化；
- 单点导航、多点导航、取消导航和初始位姿设置；
- 电量、速度通路、网关、运动模式、速度、里程计和 Nav2 状态；
- 按住才运动的手动控制，支持页面按钮和键盘；
- 手动线速度、转向速度调节，不改变 Nav2 已验证的速度配置；
- 登录、HttpOnly 会话、CSRF、防跨站 WebSocket、单操作员控制权；
- 浏览器只能通过白名单代理订阅 ROS 数据，不能直接发布 `/cmd_vel`；
- UDP 序号、会话、CRC、限速、ACK 与双端 watchdog。

## 控制链路

```text
外载 Jetson 192.168.0.101
  Nav2 /cmd_vel 或 Web /go2/manual_cmd_vel
                  │
                  │ UDP 20 Hz（eth0）
                  ▼
内载计算机 192.168.123.18
  go2_cmd_gateway（校验、限速、watchdog）
                  │
                  │ Unitree 原生 SportClient / DDS
                  ▼
Go2 下位机 192.168.123.161
```

`eth1` 独立连接 MID360S（`192.168.1.158`），不得承担 Go2 控制流量。

## 外载 Jetson 安装

依赖 ROS 2 Foxy、`rosbridge_server`、Node.js 20 和当前工作空间中的导航依赖。

```bash
cd /home/nvidia/Go2_Nav_ws
bash src/Go2_control_gateway/scripts/install_external_services.sh
```

安装器会依次测试并构建 React 前端、构建 ROS 包、安装 systemd 服务，并在首次安装时交互式
设置 `operator` 密码。仓库不保存明文密码。

目标机未安装 Node.js、但仓库已包含经过测试的生产 bundle 时，可显式跳过前端重建：

```bash
GO2_SKIP_FRONTEND_BUILD=1 \
  bash src/Go2_control_gateway/scripts/install_external_services.sh
```

```bash
systemctl status go2-console.service
systemctl status go2-console-rosbridge.service
journalctl -u go2-console.service -f
```

浏览器访问：

```text
http://192.168.0.101:8080
```

rosbridge 只监听 `127.0.0.1:9090`，不应从局域网直接访问。

## 构建与测试

```bash
cd src/Go2_control_gateway
bash scripts/build_frontend.sh
python3 -m pytest -q
```

仅测试前端：

```bash
cd frontend
npm ci
npm test -- --run
npm run lint
npm run build
```

内载网关 dry-run：

```bash
cmake -S internal_gateway -B /tmp/go2_gateway_build \
  -DGO2_GATEWAY_BUILD_SDK=OFF
cmake --build /tmp/go2_gateway_build -j2
cd /tmp/go2_gateway_build && ctest --output-on-failure
```

详细 IP、网卡职责、操作步骤与恢复方法见
[`docs/operations.md`](docs/operations.md)。
