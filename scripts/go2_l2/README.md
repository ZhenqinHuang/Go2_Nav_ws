# Go2 机载 L2 → FAST-LIO2

本目录提供 Unitree Go2 机载 4D LiDAR L2 的只读输入检查和 FAST-LIO2
启动入口。它与 `scripts/mid360` 相互独立，不会替换 MID360 配置。

## 安全边界

- 输入探针只订阅 `/utlidar/cloud` 和 `/utlidar/imu`。
- 启动脚本只运行探针和 FAST-LIO2。
- 本目录不包含机器狗运动控制接口。
- 静止验证无需移动机器狗。
- 动态建图前必须重新取得用户明确授权。

## 文件

| 路径 | 用途 |
|---|---|
| `config/go2_l2.yaml` | L2 专用 FAST-LIO2 参数 |
| `l2_input_probe.py` | 点云字段、频率、时间和型号只读检查 |
| `run_fastlio2_l2.sh` | 带输入门禁的前台启动脚本 |
| `tests/` | 不依赖 ROS 的配置和探针测试 |

## 仅检查输入

在 Jetson 上运行：

```bash
cd /home/nvidia/Go2_Nav_ws
UNITREE_INTERFACE=eth0 \
  bash scripts/go2_l2/run_fastlio2_l2.sh --probe-only
```

成功时会生成：

```text
/tmp/go2_l2_input_report.json
```

只有报告中的 `ready_for_fastlio2` 为 `true` 时，才进入 FAST-LIO2
静止启动测试。

## 启动 FAST-LIO2

机器人保持静止：

```bash
cd /home/nvidia/Go2_Nav_ws
UNITREE_INTERFACE=eth0 \
  bash scripts/go2_l2/run_fastlio2_l2.sh
```

脚本会先运行 6 秒输入探针，通过后才以前台方式启动 FAST-LIO2。
按 `Ctrl+C` 可停止。第一次验证默认不开 RViz、不保存 PCD。

限时静止测试：

```bash
timeout --signal=INT --kill-after=5 35 \
  bash scripts/go2_l2/run_fastlio2_l2.sh \
  > /tmp/go2_l2_fastlio2.log 2>&1
```

`--skip-probe` 只用于已经保存且检查通过的同一次测试会话，不应作为日常默认。

## 本地测试

```bash
python3 -m unittest -v \
  scripts.go2_l2.tests.test_l2_fastlio_assets \
  scripts.go2_l2.tests.test_l2_input_probe \
  scripts.go2.tests.test_go2_closed_loop_motion
```
