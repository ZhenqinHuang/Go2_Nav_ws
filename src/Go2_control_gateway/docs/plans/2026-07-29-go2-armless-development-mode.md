# Go2 无 Arm 开发模式实施计划

> 设计依据：`docs/plans/2026-07-29-go2-armless-development-mode-design.md`

目标：删除 Arm/Disarm 业务流程，使外载速度可直接通过 UDP 交给内载原生 SportClient，同时保留零速启动、ACK、CRC、序号、速度超时和内载看门狗。

实施原则：每一项先写失败测试，再写最小实现；部署后只进行零速度和状态验证，运动测试必须再次取得用户确认。

## 任务 1：SDK worker 自动执行首次运动准备

涉及文件：

- 修改 `internal_gateway/test/pumped_sport_api_test.cpp`
- 修改 `internal_gateway/include/go2_gateway/pumped_sport_api.hpp`
- 修改 `internal_gateway/src/pumped_sport_api.cpp`

步骤：

1. 新增测试：首个 `Move()` 立即返回，即使后端 `BalanceStand()` 阻塞。
2. 新增测试：后台先调用一次 `BalanceStand()`，成功后才调用 `Move()`。
3. 新增测试：停止后再次 Move 不重复 BalanceStand；错误可由 `PollError()` 读取。
4. 运行 C++ 单测，确认新测试先失败：

   ```bash
   cmake --build internal_gateway/build --target pumped_sport_api_test
   ctest --test-dir internal_gateway/build -R pumped_sport_api_test --output-on-failure
   ```

5. 在 worker 中加入一次性 `prepared_` 状态；准备成功后重新读取最新速度再调用后端 Move。
6. 重跑测试至通过。

## 任务 2：内载网关删除 Arm 状态门控

涉及文件：

- 修改 `internal_gateway/test/gateway_core_test.cpp`
- 修改 `internal_gateway/include/go2_gateway/gateway_core.hpp`
- 修改 `internal_gateway/src/gateway_core.cpp`

步骤：

1. 将测试改为 token 0、flags NONE 的首个非零速度帧可直接调用 pump 的 `Move()`。
2. 新增/调整测试：
   - 零速度调用 `StopMove()`；
   - 非法 token 或 Arm flag 不进入运动；
   - 失去有效帧超过 0.5 秒后调用 `StopMove()`；
   - CRC、源地址和序号校验不退化；
   - SDK worker 错误导致停止并在 ACK 中报告故障。
3. 运行 gateway core 测试，确认先失败。
4. 删除 `Locked → Arming → Armed` 的业务分支，普通合法帧直接进入速度处理。
5. 看门狗依据当前是否存在运动目标工作，不再依据 armed 状态。
6. 保留旧包字段和 ACK 布局作为线协议兼容。
7. 重跑 `gateway_core_test` 和全部 CTest。

## 任务 3：外载 sender 删除 Arm token 和门控

涉及文件：

- 修改 `test/test_sender_core.py`
- 修改 `test/test_udp_sender_adapter.py`
- 修改 `go2_control_gateway/udp_sender_node.py`
- 按实际定义位置修改 sender core

步骤：

1. 测试首个新鲜 Nav2 或手动命令无需 armed 即生成 token 0 普通速度帧。
2. 测试启动、命令超时、Nav2/手动互锁仍产生零速度。
3. 测试 token 0 ACK 继续更新链路在线和 RTT。
4. 删除 arm/disarm pending、token 生成、armed 门控及 ROS Arm 服务。
5. 状态增加 `control_ready`（网关在线且 ACK 新鲜）；兼容字段如保留则固定为 false，不再参与逻辑。
6. 运行相关 pytest 至通过。

## 任务 4：冒烟测试删除 Arm/Disarm

涉及文件：

- 修改 `test/test_smoke_test_core.py`
- 修改 `test/test_smoke_test_node.py`
- 修改 `test/test_ros_adapter_compat.py`
- 修改 `go2_control_gateway/smoke_test_core.py`
- 修改 `go2_control_gateway/smoke_test_node.py`

步骤：

1. 将测试流程改为：等待状态 → 检查在线/ACK/Nav2 → 发送速度 → finally 连续发送零速度。
2. 删除 adapter 的 arm/disarm 调用要求。
3. 保留“无 ACK、Nav2 活跃、状态超时则绝不发送非零速度”的测试。
4. 运行 smoke 相关 pytest 至通过。

## 任务 5：Web 和 HTTP API 删除 Arm/Disarm

涉及文件：

- 修改 `test/test_console_http.py`
- 修改 `test/test_console_core.py`
- 修改 `test/test_web_contract.py`
- 修改 `go2_control_gateway/console_server.py`
- 修改 `go2_control_gateway/console_core.py`
- 修改 `frontend/src/api/consoleClient.ts`
- 修改 `frontend/src/api/consoleClient.test.ts`
- 修改 `frontend/src/components/controlPolicy.test.ts`
- 修改 `frontend/src/App.tsx`
- 必要时修改 `frontend/src/App.css`

步骤：

1. 更新契约测试：HTTP 不再提供 Arm/Disarm 操作，页面不显示对应按钮。
2. 将手动控制条件改为：

   ```text
   gateway_link == online AND has_control_lease AND nav_active == false
   ```

3. 停止按钮直接发布零速度，不依赖 Disarm。
4. 删除 Web client 的 arm/disarm 方法和服务端路由。
5. 运行 Python Web 契约测试及前端测试。
6. 构建前端产物并确认没有 Arm/Disarm 操作文字。

## 任务 6：全量验证与文档同步

步骤：

1. 本地全量 Python 测试：

   ```bash
   python -m pytest -q
   ```

2. 内载网关全量构建和测试：

   ```bash
   cmake -S internal_gateway -B internal_gateway/build
   cmake --build internal_gateway/build
   ctest --test-dir internal_gateway/build --output-on-failure
   ```

3. 前端测试和构建：

   ```bash
   npm --prefix frontend test -- --run
   npm --prefix frontend run build
   ```

4. ROS 2 workspace 构建：

   ```bash
   colcon build --packages-select go2_control_gateway
   ```

5. 更新教程和部署文档中的 Arm 操作，使其与无 Arm 控制链路一致。
6. 检查 git diff，确保不纳入已有的无关改动。

## 任务 7：部署和零速度验收

步骤：

1. 备份外载和内载当前可执行文件及配置。
2. 将新内载网关部署到 systemd 服务路径，重启后检查单实例和 UDP 端口。
3. 将新外载 sender、console 和前端产物部署并重启服务。
4. 不启动 Nav2，不调用运动冒烟测试，只确认：
   - 外载持续发送 token 0 零速度帧；
   - 内载 ACK 持续返回；
   - 网关连接显示 online；
   - ACK 延迟和序号正常；
   - 内载没有持续 Move 调用；
   - Web 不再显示 Arm/Disarm。
5. 只有在上述检查全部通过后，向用户报告拟测试速度、距离和时长，等待明确确认再进行真机运动测试。
