# Go2 control gateway

本包实现机器狗正式运动边界：外载 Jetson 只发送受控 UDP，内载计算机校验后调用 Unitree
`SportClient`。Web 控制台由 `Go2_web_console` 独立维护。

```text
Jetson 192.168.123.5
  Nav2 /cmd_vel 或 Web /go2/manual_cmd_vel
  -> go2_cmd_vel_udp_sender :15001 -> 192.168.123.18:15000
  -> 内载 go2_cmd_gateway
  -> Unitree SportClient / DDS
  -> 192.168.123.161
```

协议包含会话、序号、CRC、Arm 令牌、限速、ACK、双端 watchdog、站立、趴下以及锁存急停。
急停后，只有通过健康检查的显式复位才能重新接收速度。

## 外载安装

```bash
cd /home/nvidia/Go2_Nav_ws
bash src/Go2_control_gateway/scripts/install_external_services.sh
sudo systemctl enable --now go2-motion-sender.service
```

该安装器只安装 sender 服务，不构建或安装 Web。Web 服务由
`src/Go2_web_console/systemd/` 管理。

## 无运动测试

```bash
python3 -m pytest -q src/Go2_control_gateway
cmake -S src/Go2_control_gateway/internal_gateway -B /tmp/go2_gateway_build \
  -DGO2_GATEWAY_BUILD_SDK=OFF
cmake --build /tmp/go2_gateway_build -j2
ctest --test-dir /tmp/go2_gateway_build --output-on-failure
```

网络、协议和服务细节见 `docs/`。首次非零速度或站立/趴下测试必须由现场人员明确授权。
