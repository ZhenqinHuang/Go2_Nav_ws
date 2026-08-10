# Web 控制台部署与运维

## 1. 前置条件

外载 Jetson：

- 局域网地址 `192.168.0.101` 可从操作电脑访问。
- ROS 2 Foxy 可用。
- `/home/nvidia/unitree_ros2/install/setup.bash` 可用。
- `/home/nvidia/Go2_Nav_ws/install/setup.bash` 可用。
- `rosbridge_server` 已安装。
- 独立运动网关已发布 ROS 接口，或使用 `--demo` 做无动作页面检查。

Web 工作空间：

```text
/home/nvidia/go2_web_console/
├── src/go2-web-console/
├── build/
├── install/
└── log/
```

## 2. 安装

```bash
cd /home/nvidia/go2_web_console/src/go2-web-console
bash scripts/install_web_console.sh
```

首次安装会交互式创建 `/etc/go2-console/password.hash`。不要把明文密码或
hash 文件复制到仓库。

安装完成后：

```bash
systemctl status go2-console.service --no-pager
systemctl status go2-console-rosbridge.service --no-pager
ss -lntp | grep -E '8080|9090'
```

期望：

- 8080 绑定 `192.168.0.101`。
- 9090 只绑定 `127.0.0.1`。
- 浏览器访问 `http://192.168.0.101:8080`。

## 3. 独立启停

```bash
sudo systemctl restart go2-console-rosbridge.service
sudo systemctl restart go2-console.service

journalctl -fu go2-console.service
journalctl -fu go2-console-rosbridge.service
```

这些命令不应操作：

```text
go2-motion-sender.service
go2-cmd-gateway.service
```

更新前端或后端无需重启运动网关。

## 4. 设置新密码

先生成临时 hash：

```bash
source /opt/ros/foxy/setup.bash
source /home/nvidia/go2_web_console/install/setup.bash
ros2 run go2_web_console go2_set_console_password \
  --output /tmp/go2-password.hash
```

再安装并重启 Web：

```bash
sudo install -m 0600 -o nvidia -g nvidia \
  /tmp/go2-password.hash /etc/go2-console/password.hash
rm -f /tmp/go2-password.hash
sudo systemctl restart go2-console.service
```

## 5. 无动作页面检查

开发机或外载可以使用 demo adapter：

```bash
export GO2_CONSOLE_DEMO_PASSWORD='<仅在当前终端设置>'
python3 -m go2_web_console.console_server \
  --demo --bind 127.0.0.1 --port 8080
```

Demo 不发布 ROS 2 运动消息，适合检查登录、布局和 Nav2/手动互斥页面状态。

## 6. 运行检查

```bash
systemctl is-active go2-motion-sender.service
pgrep -af 'go2_cmd_vel_udp_sender|udp_sender.launch.py'
ss -lunp | grep 15001
ros2 topic echo /go2_cmd_vel_gateway/status
ros2 topic info /go2/manual_cmd_vel
ros2 action list | grep navigate
ros2 topic hz /odom
```

预期只有独立 `go2-motion-sender.service` 对应的一个 sender，UDP 15001 也只有
一个进程监听。页面网关离线时，先检查运动网关 ROS 状态，不要尝试让 Web 直接
使用 UDP。

页面操作流程：

1. 登录后点击左侧“底盘控制”展开停靠栏；
2. 检查“网关连接”为在线且“控制就绪”为是；
3. 若 Nav2 活跃，先点击“取消导航”并等待其结束；
4. 点击“接管控制”取得单操作员租约；
5. 按住前进、后退、左转或右转按钮运动，松开立即停车；
6. 完成后点击“释放控制”，再收起停靠栏。

停靠栏默认收起并固定在左侧，展开后不覆盖右侧原有的任务/路径面板。当前已验证
底层配置 `max_vy=0.0`，因此页面不提供横移按钮。

## 7. 故障排查

### 页面打不开

```bash
systemctl status go2-console.service --no-pager
journalctl -u go2-console.service -n 100 --no-pager
ss -lntp | grep 8080
```

确认浏览器与 `192.168.0.101` 在同一局域网。

### 可登录但没有可视化

检查 9090 是否只监听 loopback，以及 rosbridge 日志。浏览器不应直接连接
9090，而是连接同源 `/ws/ros`。

### 手动控制不可用

依次确认：

1. `go2-motion-sender.service` 正在运行，且旧 sender 没有占用 UDP 15001。
2. 外载 `eth0` 有 carrier，并持有 `192.168.123.5/24`。
3. `ip route get 192.168.123.18` 显示 `dev eth0 src 192.168.123.5`。
4. 网关状态为 online/control_ready，ACK 年龄小于 0.5 秒。
5. 页面已取得控制租约。
6. Nav2 不处于 ACCEPTED/EXECUTING/CANCELING。
7. 如导航活跃，先点击“取消导航”并等待状态结束。

若 `eth0` 为 `NO-CARRIER`，内载板未上电、USB 转网线未连接或链路未协商成功，
系统可能临时通过 WLAN 默认路由查找 `192.168.123.18`。此时页面必须保持
fail-closed，不能发送非零速度；先恢复物理链路，再检查静态地址和路由。

### Web 重启后速度归零

这是预期行为。Web 断开和 cleanup 会发送零速度；重新登录后需重新取得人工
控制租约。Nav2 自身速度链路不依赖 Web。

## 8. 回退

保留上一个工作空间安装和 systemd 文件。回退时只替换 Web 包和两个 Web
服务，不改动运动网关。完成后验证登录、状态、零速度与 Nav2 状态；真机动作
仍需单独确认。
