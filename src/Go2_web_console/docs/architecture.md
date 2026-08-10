# Web 控制台架构

## 1. 运行边界

```text
浏览器
  │ HTTPS/HTTP API + WebSocket
  ▼
go2_console（aiohttp，192.168.0.101:8080）
  ├─ 登录、CSRF、速率限制、控制租约
  ├─ 固定 ROS 2 适配器
  └─ 只读 rosbridge 代理
       │ ws://127.0.0.1:9090
       ▼
rosbridge_server（仅 loopback）

固定 ROS 2 适配器
  ├─ /go2/manual_cmd_vel ──> 独立运动网关
  ├─ gateway status <────── 独立运动网关
  ├─ Nav2 action/service
  └─ 机器人状态 topic
```

浏览器不能提交任意 topic、service 或 action 名称。所有可用操作都由
`ros_adapter.py` 和 `readonly_rosbridge.py` 中的固定白名单定义。

## 2. 后端模块

| 文件 | 职责 |
|---|---|
| `console_core.py` | 登录、session、控制租约、Nav2/手动互斥和手动 watchdog |
| `console_server.py` | HTTP API、WebSocket、CSRF、限流和静态资源 |
| `ros_adapter.py` | 固定 ROS 2 topic/service/action |
| `readonly_rosbridge.py` | 可视化只读白名单 |
| `set_console_password.py` | 本地密码哈希生成 |

后端的停止路径：

- 控制租约释放或超时发送零速度。
- WebSocket 断开发送零速度。
- logout 发送零速度。
- 服务清理发送零速度。
- 紧急停止先发送零速度，再调用网关停止服务。

这些是 Web 侧保护；底层 ACK 超时和内载 watchdog 仍由运动网关独立负责。

## 3. 前端模块

前端提供：

- 登录。
- 状态总览。
- 手动速度控制。
- 地图、机器人模型和 ROS 可视化。
- 初始位姿。
- 单点与多点 Nav2 目标。
- 导航取消。

前端只调用同源 `/api/*`、`/ws/state` 和 `/ws/ros`，不直接暴露公网
rosbridge。

## 4. 手动与 Nav2 互斥

控制规则：

1. 用户登录。
2. 页面取得控制租约。
3. 网关在线且 Nav2 不活跃时允许手动速度。
4. Nav2 状态为 `ACCEPTED`、`EXECUTING` 或 `CANCELING` 时，手动速度被拒绝。
5. 用户必须点击“取消导航”，等待 Nav2 结束后才能重新取得人工控制。
6. 页面速度调节只改变手动速度；Nav2 速度参数仍由导航配置管理。

## 5. 独立部署

Web 与运动进程使用不同 systemd 单元。更新 Web 时只重启 console 和
rosbridge，不重启 motion sender。Web 完全停止时，Nav2 到底盘的运动链路
仍可运行。
