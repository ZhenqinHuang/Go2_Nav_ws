# 拆分验证记录

日期：2026-07-29

## 后端

```text
python -m pytest -q
54 passed

python -m compileall -q go2_web_console
PASS
```

仓库边界测试确认：

- 不存在 `internal_gateway`。
- 不存在 UDP protocol、sender core 或 sender node。
- ROS 适配器不包含 UDP 端口和 `SportClient`。
- Web 安装脚本不管理运动网关服务。

## 前端

```text
npm ci
PASS

npm test -- --run
3 files / 24 tests passed

npm run lint
0 errors / 67 existing warnings

npm run build
PASS
```

90 个 Git 跟踪的前端文件已与集成基线逐项检查，全部复制成功，包括中文名称
的导航与页面截图。生产 bundle 已重新输出到 `go2_web_console/web`。

浏览器交互检查确认：

- 底盘控制默认收起，展开后位于左侧，不与右侧任务/路径面板重叠；
- 鼠标按住前进按钮期间连续产生 `POST /api/manual`；
- 按下请求体为 `{"vx":0.25,"vy":0,"vyaw":0}`；
- 松开请求体为 `{"vx":0,"vy":0,"vyaw":0}`；
- pointer cancel、lost capture、窗口失焦和页面隐藏均走零速度路径；
- 测试使用 demo adapter，未向真机发送非零指令。

当前依赖审计报告 5 个 high severity 问题。没有在拆分任务中执行
`npm audit fix --force`，因为它会升级或替换依赖并可能改变已验证页面行为。
依赖升级应作为独立任务，在前端回归测试和页面验证后处理。
