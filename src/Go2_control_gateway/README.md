# go2_control_gateway

外载 Jetson 到内载计算机的 fail-closed 速度网关和局域网控制台。

主要组件：

- `go2_cmd_vel_udp_sender`：订阅 Nav2 `/cmd_vel` 和手动速度，以 20 Hz 发往内载。
- `internal_gateway/go2_cmd_gateway`：校验 UDP，管理 Arm/watchdog，通过原生 Unitree SDK 执行。
- `go2_console`：`aiohttp + rclpy` 的认证控制台，默认监听 `192.168.0.101:8080`。
- `go2_set_console_password`：交互式生成 scrypt 密码哈希。

## 外载构建与测试

```bash
source /opt/ros/foxy/setup.bash
colcon build --packages-select go2_control_gateway
source install/setup.bash
python3 -m pytest src/Go2_control_gateway/test -q
```

本地无机器人 demo：

```bash
export GO2_CONSOLE_DEMO_PASSWORD='仅用于本地测试的密码'
ros2 run go2_control_gateway go2_console --demo --bind 127.0.0.1 --port 18080
```

demo 不调用真实 ROS 运动接口。

## 内载 dry-run

```bash
cmake -S src/Go2_control_gateway/internal_gateway \
  -B /tmp/go2_gateway_build \
  -DGO2_GATEWAY_BUILD_SDK=OFF
cmake --build /tmp/go2_gateway_build -j2
cd /tmp/go2_gateway_build && ctest --output-on-failure
python3 src/Go2_control_gateway/internal_gateway/test/udp_integration_test.py \
  --gateway /tmp/go2_gateway_build/go2_cmd_gateway
```

真实内载安装：

```bash
bash src/Go2_control_gateway/scripts/deploy_internal_gateway.sh
```

外载服务安装：

```bash
bash src/Go2_control_gateway/scripts/install_external_services.sh
```

完整网络、操作和故障恢复说明见
[`docs/go2-control-network-and-console.md`](../../docs/go2-control-network-and-console.md)。
