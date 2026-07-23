# Go2 实机诊断工具

本目录包含会与真实 Go2 通信的诊断工具。任何运动测试都必须获得现场人员的当次
明确授权；历史授权、接线确认或“继续排查”均不能代替当次授权。

## 闭环前进测试

`go2_closed_loop_motion_test.py` 使用 `/lf/sportmodestate` 的位置反馈停止运动，
并在以下任一条件出现时发送一组 StopMove：

- 达到提前停车阈值；
- 状态数据超过 0.15 秒未更新；
- 检测到其他 Sport API 请求；
- 反向移动、横向偏移或总位移超过安全范围；
- 达到运动硬超时；
- 收到 SIGINT 或 SIGTERM；
- 程序异常退出。

先运行不连接机器狗的纯逻辑测试：

```bash
cd /home/nvidia/Go2_Nav_ws
python3 -m unittest -v scripts.go2.tests.test_go2_closed_loop_motion
```

实机命令和安全检查清单见：

```text
docs/go2/控制验证记录_2026-07-23.md
```

不要把 `--armed YES` 当成安全授权；它只用于阻止脚本被无意启动。
