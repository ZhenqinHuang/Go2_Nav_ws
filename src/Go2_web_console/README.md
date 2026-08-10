# Go2 Web Console

运行在外载 Jetson 上的独立 Go2 局域网控制台，提供登录认证、机器人状态、
人工速度控制、地图可视化和 Nav2 目标操作。

本仓库不包含 UDP、内载 C++ 网关或 Unitree SportClient。底盘运动由独立
[`ZhenqinHuang/go2-motion-gateway`](https://github.com/ZhenqinHuang/go2-motion-gateway)
处理，Web 只依赖其公开 ROS 2 接口。

## 功能

- 局域网登录与 session/CSRF 保护。
- 单操作员控制租约。
- 前进、后退、转向和显式停止。
- 站立、趴下和紧急停止。
- 电量、网关连接、运动模式、速度、里程计和 Nav2 状态。
- 初始位姿设置。
- Nav2 单点目标、多点目标和取消导航。
- 登录后只读 rosbridge 可视化代理。
- Nav2 活跃时禁止手动运动，必须先人工取消导航。
- 底盘控制以左侧可折叠停靠栏呈现，默认收起，不遮挡原地图与任务面板。
- 按住方向按钮持续发送真实速度，松开、失焦或页面隐藏立即发送零速度。

## 仓库边界

```text
go2_web_console/  Python HTTP 后端、ROS 白名单适配器、生产前端资源
frontend/         React 19 + TypeScript + Vite 源码
config/           Web 配置
systemd/          Web 与 loopback rosbridge 服务
scripts/          前端构建和 Web-only 安装
test/             后端、接口和仓库边界测试
docs/             架构、ROS 接口和运维
```

禁止在本仓库中实现：

- 外载—内载 UDP 协议。
- 速度 sender 或 ACK 状态机。
- 内载网关。
- Unitree SDK 控制。
- Go2 下位机直连。

## 开发机验证

后端：

```bash
python3 -m pytest -q
python3 -m compileall -q go2_web_console
```

前端：

```bash
cd frontend
npm ci
npm test -- --run
npm run lint
npm run build
```

生产构建输出到 `go2_web_console/web`，由 Python 后端在 8080 端口提供。

## 外载部署

建议 ROS 2 工作空间：

```text
/home/nvidia/go2_web_console/src/go2-web-console
```

执行：

```bash
cd /home/nvidia/go2_web_console/src/go2-web-console
bash scripts/install_web_console.sh
```

浏览器访问：

```text
http://192.168.0.101:8080
```

首次安装会在终端提示设置 Web 密码，密码哈希只写入外载本地
`/etc/go2-console/password.hash`，不会写入 GitHub。

Web 安装脚本只管理：

- `go2-console.service`
- `go2-console-rosbridge.service`

它不会停止、重启或更新 `go2-motion-sender.service`。

实际移动前必须先确认独立发送器和内载网关已经在线。页面依次点击
“底盘控制”与“接管控制”，只有在 `gateway_link=online`、
`control_ready=true` 且 Nav2 未运行时才启用方向按钮。页面调用
`POST /api/manual`，后端将速度发布到 `/go2/manual_cmd_vel`；Web 不直接访问
UDP 或 Unitree SDK。

详细步骤见 [`docs/operations.md`](docs/operations.md)，接口边界见
[`docs/ros-interface.md`](docs/ros-interface.md)。

## 许可与来源

前端基于 `ljh_robot_ros2_web`，其许可文件完整保留在
[`frontend/LICENSE`](frontend/LICENSE)，适用
CC BY-NC-SA 4.0。前端文件中的原作者署名和版权说明继续保留。使用者在发布
修改版本前应自行确认该非商业、相同方式共享许可满足使用场景。
