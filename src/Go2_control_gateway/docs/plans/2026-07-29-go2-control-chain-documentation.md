# Go2 Control Chain Documentation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 生成两份以当前源码为准的 Markdown 文档，使没有项目背景的工程师能够理解并打通外载 Jetson NX、内载板卡与 Go2 下位机之间的控制链路。

**Architecture:** 文档一按物理层、网络层、ROS 2 层、UDP 协议层、内载状态机和 Unitree SDK 层解释系统；文档二按部署、启动、调用、验收、停机和排障顺序提供现场 Runbook。两份文档互相引用，并从仓库 README 提供入口。

**Tech Stack:** Markdown、ROS 2 Foxy、Python 3.8/rclpy/aiohttp、UDP、C++17、Unitree Go2 SDK/SportClient、systemd、NetworkManager、React。

---

### Task 1: 编写架构与接口说明

**Files:**
- Create: `docs/Jetson_NX到Go2_控制链路架构与接口.md`
- Reference: `go2_control_gateway/protocol.py`
- Reference: `go2_control_gateway/sender_core.py`
- Reference: `go2_control_gateway/udp_sender_node.py`
- Reference: `go2_control_gateway/console_server.py`
- Reference: `go2_control_gateway/ros_adapter.py`
- Reference: `internal_gateway/include/go2_gateway/protocol.hpp`
- Reference: `internal_gateway/src/gateway_core.cpp`
- Reference: `internal_gateway/src/unitree_sport_api.cpp`

**Step 1: 建立文档骨架**

写入目标、读者、硬件拓扑、IP 表、端口表和端到端数据流。

**Step 2: 补充接口契约**

列出 ROS 话题、服务、Action、HTTP API、WebSocket、UDP 控制帧和 ACK 字段。

**Step 3: 补充安全状态机**

解释外载命令选择、定位保护、ACK 超时、内载 LOCKED/ARMING/ARMED、令牌撤销和 watchdog。

**Step 4: 补充源码清单**

按“核心新增文件、Web 融合文件、部署文件、测试文件”分组说明职责。

**Step 5: 运行结构检查**

Run:

```powershell
rg -n "^# |^## |192\\.168\\.|15000|15001|/cmd_vel|SportClient|LOCKED|ARMING|ARMED" "docs/Jetson_NX到Go2_控制链路架构与接口.md"
```

Expected: 所有主要章节、IP、端口、核心接口和状态均至少出现一次。

### Task 2: 编写部署与联调 Runbook

**Files:**
- Create: `docs/Jetson_NX到Go2_控制链路部署联调日志.md`
- Reference: `scripts/deploy_internal_gateway.sh`
- Reference: `scripts/install_external_services.sh`
- Reference: `systemd/go2-cmd-gateway.service`
- Reference: `systemd/go2-console.service`
- Reference: `systemd/go2-console-rosbridge.service`
- Reference: `config/udp_sender.yaml`
- Reference: `config/internal_gateway.env`
- Reference: `config/console.yaml`

**Step 1: 写入部署前检查**

包括安全条件、网线、IP、NetworkManager、路由、SDK 和 ROS 依赖。

**Step 2: 写入构建与安装**

分别提供外载和内载的复制命令、安装位置、服务启动方式和预期监听端口。

**Step 3: 写入调用方法**

覆盖 Web 正常操作、ROS CLI、Nav2 Action、只读 HTTP/API 检查；运动命令紧邻 Disarm。

**Step 4: 写入分级验收**

先做无运动检查，再做低速短距离手动测试，最后做 Nav2 全链路测试。

**Step 5: 写入排障和日志模板**

覆盖路由错误、网关离线、Arm 失败、下位机 DDS/SDK 错误、Nav2 互锁和断线恢复。

**Step 6: 运行命令关键字检查**

Run:

```powershell
rg -n "ip route get|nmcli|ping -I|colcon build|cmake|systemctl|journalctl|ros2 (topic|service|action)|Disarm|StopMove" "docs/Jetson_NX到Go2_控制链路部署联调日志.md"
```

Expected: 网络、构建、服务、ROS 调用、安全停止和排障命令均存在。

### Task 3: 增加仓库入口和交叉链接

**Files:**
- Modify: `README.md`
- Modify: `docs/Jetson_NX到Go2_控制链路架构与接口.md`
- Modify: `docs/Jetson_NX到Go2_控制链路部署联调日志.md`

**Step 1: 在 README 增加文档入口**

添加两个相对链接，并说明阅读顺序。

**Step 2: 在两份文档顶部互相引用**

架构文档指向 Runbook，Runbook 指向架构文档。

**Step 3: 检查引用文件存在**

Run:

```powershell
@(
  "docs/Jetson_NX到Go2_控制链路架构与接口.md",
  "docs/Jetson_NX到Go2_控制链路部署联调日志.md"
) | ForEach-Object { if (-not (Test-Path $_)) { throw "missing $_" } }
```

Expected: exit code 0。

### Task 4: 完整验证与提交

**Files:**
- Verify: all modified documentation

**Step 1: 扫描凭据和危险占位**

Run:

```powershell
rg -n -i "password\\s*[:=]|passwd|sshpass|token\\s*[:=]|secret\\s*[:=]" README.md docs
```

Expected: 无明文凭据命中。

**Step 2: 验证源码引用**

从文档代码路径中抽样并使用 `Test-Path` 验证关键文件存在。

**Step 3: 运行项目测试**

Run:

```powershell
python -m pytest -q
cd frontend
npm test -- --run
npm run build
```

Expected: Python 现有测试通过；前端 23 项测试通过；生产构建成功。

**Step 4: 检查差异**

Run:

```powershell
git diff --check
git status --short
```

Expected: 无空白错误；仅包含计划内的 Markdown 和 README 修改。

**Step 5: 提交**

```bash
git add README.md docs
git commit -m "docs: add end-to-end Go2 control chain runbooks"
```
