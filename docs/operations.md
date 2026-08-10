# 启动与操作

## 推荐启动

```bash
cd /home/nvidia/Go2_Nav_ws
bash scripts/check_system.sh
bash scripts/start_navigation.sh
```

首次调试仍可按终端拆分：Livox、FAST-LIO2、odom bridge、三维定位、pc2scan、控制网关、Nav2、Web。

## 发送目标前的通过条件

- `/map` 有且只有预期 map_server 发布；
- `/odom`、`/scan`、`/map_to_odom` 持续更新且未超时；
- `map -> base_link` 可查询且稳定；
- Nav2 lifecycle active；
- `go2-motion-sender` 有新鲜的内载 ACK；
- Web 状态为 `ready`，急停未锁存；
- 当前用户持有控制租约。

## Web 控制

访问 `http://192.168.0.101:8080`。手动方向键采用按住运动、释放归零；页面失焦、连接断开和租约超时都必须归零。

只保留站立和趴下：两者均要求速度为零且导航停止，趴下需要二次确认。急停对所有已登录用户可用；复位要求持有租约且系统重新通过健康检查。

## 首次实机目标

先验证急停和复位，再发送 0.5～1 m 的无遮挡目标。观察地图、点云、机器人位姿、局部代价地图和实际运动方向，确认一致后再扩大距离。

## 停止

使用 `bash scripts/stop_all.sh`。停止顺序必须先取消导航、确认速度归零，再终止 Nav2 和感知进程。不要用模糊的全局 `pkill` 清理无关 ROS 进程。
