# Go2 控制网关验收清单

日期：2026-07-28  
目标链路：外载 Nav2 → UDP → 内载 `go2_cmd_gateway` → Unitree 原生 SDK → Go2 下位机

## 已完成的离线与外载验证

- [x] Python 协议固定 56 字节、网络字节序、黄金向量和 CRC。
- [x] 外载 sender 的 Arm、ACK 超时、cmd 超时、定位保护、限速和旧令牌撤销。
- [x] Web 登录、CSRF、单控制租约、Nav2 互锁、松开/断连归零。
- [x] 控制台桌面与 390 px 移动端真实浏览器冒烟测试。
- [x] 外载 Jetson aarch64 上编译 C++17 协议和 `GatewayCore`。
- [x] C++ 测试覆盖 BalanceStand、ARMING、Move、StopMove、重放、watchdog、Disarm、SDK 错误和二次限速。
- [x] `go2_cmd_gateway --dry-run` UDP 回环测试覆盖 ACK 关联、坏 CRC 丢弃、0.5 秒失联锁定和旧令牌拒绝。
- [x] systemd 单元校验和部署 shell 语法检查。
- [x] 外载 Jetson Ubuntu 20.04 / ROS 2 Foxy / Python 3.8 原生构建通过，网关包测试 `79 passed`。
- [x] 外载真实 ROS sender 与 C++ dry-run gateway 回环闭环通过：在线、Arm ACK、ARMED、Disarm、LOCKED。
- [x] 源码已部署到 `/home/nvidia/Go2_Nav_ws`；部署前文件已备份到 `.codex_backups/go2-udp-gateway-20260728-200846`。

当前外载的 `eth0` 和 `eth1` 都无载波，保存的 NetworkManager 配置正确，但内载断电时
`192.168.123.18` / `192.168.123.161` 会暂时按默认路由查询到 `wlan0`。这不是配置
回退；内载和网线恢复后必须再次确认这两个目标均由 `eth0` 直连。

## 内载重新上电后的无运动验收

- [ ] 暂未验证：从内载源码执行 `GO2_GATEWAY_BUILD_SDK=ON` 构建成功。
- [ ] 暂未验证：`ldd go2_cmd_gateway` 无 `not found`。
- [ ] 暂未验证：内载服务绑定 `192.168.123.18:15000`，接口为 `eth0`。
- [ ] 暂未验证：服务启动立即调用 StopMove，Web 显示网关在线但 LOCKED。
- [ ] 暂未验证：错误来源 IP、坏 CRC、NaN、重放包不会改变状态或刷新 watchdog。
- [ ] 暂未验证：Arm 后先进入 ARMING，约 0.8 秒后才变为 ARMED。
- [ ] 暂未验证：拔掉/禁用外载控制链路后 0.5 秒内 StopMove、LOCKED、旧令牌失效。
- [ ] 暂未验证：重启内载或外载后不会自动恢复 Arm。

建议命令：

```bash
systemctl status go2-cmd-gateway.service
journalctl -u go2-cmd-gateway.service -f
ss -lunp | grep 15000
```

## 实机低速验收

以下步骤必须由现场人员确认机器人已离开充电器、四脚着地且前方安全后再做：

- [ ] 暂未验证：控制台登录和接管控制。
- [ ] 暂未验证：Arm 二次确认后 Go2 完成站立准备并显示 ARMED。
- [ ] 暂未验证：按住前进，以不高于 `0.2 m/s` 行走约 `0.4 m`，松开立即停止。
- [ ] 暂未验证：左右转向方向正确，`vy` 始终为 0。
- [ ] 暂未验证：点击 Disarm 后所有手动键禁用，状态回到 LOCKED。
- [ ] 暂未验证：Nav2 活跃时手动 API 和页面控制均被拒绝。
- [ ] 暂未验证：人工取消导航、状态变为 IDLE 后才能重新手动控制。
- [ ] 暂未验证：完整 Nav2 `/cmd_vel` 能经新路径驱动底盘。

## 验收记录

| 项目 | 结果 | 时间 | 操作员 / 备注 |
|---|---|---|---|
| 外载 Python 3.8 构建与 79 项测试 | 通过 | 2026-07-28 | Codex / 外载现场工作区 |
| 外载 ROS sender → C++ dry-run 闭环 | 通过 | 2026-07-28 | Arm、ACK、Disarm、LOCKED |
| 内载 SDK 构建 | 待测 |  |  |
| 无运动 Arm / Disarm | 待测 |  |  |
| 0.5 秒失联保护 | 待测 |  |  |
| 0.4 m 手动前进 | 待测 |  |  |
| Nav2 全链路 | 待测 |  |  |

在所有“暂未验证”项目完成前，不得把当前版本描述为已完成新网关的实机验收。
