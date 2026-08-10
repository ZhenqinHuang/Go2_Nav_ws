# 验证报告 — 2026-08-10

## 结论

提交 `a9e7854` 已通过本地测试和 Jetson 零运动 staging 验证。验证期间未替换
`/etc/systemd/system` 文件，未停止或重启现网服务，未启动 Livox、FAST-LIO2、定位或
Nav2，也未发送非零速度、站立或趴下指令。

已验证版本：

```text
Jetson: 192.168.0.101
staging: /home/nvidia/Go2_Nav_ws_staging/go2-nav-a9e7854-20260810T1550
archive SHA-256: 4a7fd30ee5df4d4d5a2b128da86fae177dc50f44ac843e987ee86191e6580b70
```

第一次暂存的 `56640dd` 暴露了 Windows CRLF 与 Git/Jetson LF 导致地图 Manifest 不一致的
问题。修复和回归测试已包含在 `a9e7854`；旧暂存目录保留为
`go2-nav-56640dd-20260810T1547.REJECTED-map-crlf`，不可用于部署。

## 本地验证

| 验证 | 结果 |
|---|---|
| Web 后端 pytest | `103 passed` |
| 外载控制网关 pytest | `70 passed` |
| 项目接口/地图/Nav2/布局测试 | `25 passed` |
| Web 前端 Vitest | `33 passed` |
| Web ESLint | `0 errors`，`67 warnings` |
| TypeScript + production build | 通过 |
| Python compileall | 通过 |
| package.xml / YAML 解析 | 通过 |
| canonical map Manifest | 通过 |

production bundle 包含 `index.html`、`icon.svg`、一个 CSS 和一个 JS 文件，不包含文档截图、
Vite logo 或旧机器人图片。

## Jetson staging 验证

目标环境为 Jetson aarch64、Ubuntu 20.04、ROS 2 Foxy。

| 验证 | 结果 |
|---|---|
| 所有 shell 脚本 `bash -n` | 通过 |
| 地图 Manifest / XML / YAML | 通过 |
| 接口 pytest | `25 passed` |
| 网关 Python pytest | `70 passed` |
| Web 后端 pytest | `103 passed` |
| 内载网关 C++ 构建 | 通过，SDK 关闭的 dry-run 配置 |
| 内载网关 CTest | `3/3 passed` |
| ROS 2 colcon 全量构建 | `10 packages finished` |
| Nav2 launch description | `--show-args` 通过，DWB/RPP 参数可见 |
| staged Web demo | root `200`、未认证 state `401`、登录 `200`、认证 state `200` |
| 当前正式 Web | root `200`、未认证 state `401` |

目标机没有独立 Node/npm，因此没有在 Jetson 重新编译前端。部署脚本确认 production bundle
完整后按设计跳过目标机重建；相同 bundle 已在本地完成 TypeScript、Vitest、lint 和 production
build。ROS 构建出现 PCL/VTK 可选 IO 组件警告，但 10 个包均成功完成。

## 当前运行态观察

2026-08-10 15:59 CST 的只读快照：

- `go2-console.service`、`go2-console-rosbridge.service`、
  `go2-motion-sender.service` 为 active；
- `go2-navigation.service`、`go2-mapping.service`、`ptp_sync.service` 未运行，后两项新模板也尚未
  安装到现网；
- `192.168.1.158` 正确走 `eth1`；
- `eth0` 无地址/载波，`192.168.123.18` 和 `192.168.123.161` 当前错误回落到 `wlan0`；
- `/go2_cmd_vel_gateway/status` 在 5 秒内没有返回状态，因此不能把 sender 的 active 等同于运动
  ready。

以上控制网络状态符合内载/Go2 断电场景，运动测试必须继续阻止。

## 尚未执行

- MID360 实时话题、FAST-LIO2、ICP 与 `map -> odom -> base_link` 验证；
- Nav2 lifecycle 和真实 `/map`、`/odom`、`/scan` 闭环；
- PTP lock；
- 非零速度、站立、趴下和真实急停/复位；
- 0.5～1 m 首次导航目标。

这些项目必须等 Go2 控制专网上电，并由现场人员明确授权后执行。

## 复验命令

```bash
RELEASE=/home/nvidia/Go2_Nav_ws_staging/go2-nav-a9e7854-20260810T1550
cd "$RELEASE"
python3 scripts/map_bundle.py validate maps
python3 -m pytest -q test/interface
python3 -m pytest -q src/Go2_control_gateway/test
python3 -m pytest -q src/Go2_web_console/test
```

正式切换与回滚命令见 [deployment.md](deployment.md)。
