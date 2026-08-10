# Go2 bringup

`go2_bringup` 实现机器狗建图和导航的统一启动顺序。日常操作只使用仓库根目录的稳定入口：

```bash
cd /home/nvidia/Go2_Nav_ws
bash scripts/check_system.sh
bash scripts/start_mapping.sh       # 建图
bash scripts/start_navigation.sh    # 导航
bash scripts/stop_all.sh
```

## 导航启动顺序

```text
Livox MID360S
  -> FAST-LIO2
  -> odom_tf_bridge
  -> fast_lio_localization_ros2
  -> go2_pc2scan
  -> Nav2
```

脚本以话题、TF 和 Action 的实际就绪状态推进，不使用固定等待时间。三维定位读取
`maps/MID360.pcd`，Nav2 的唯一 `map_server` 读取 `maps/MID360_map.yaml`。

`CONTROLLER=dwb` 为默认配置；设置 `CONTROLLER=rpp` 可切换 RPP。运动输出始终走
`go2-motion-sender.service` 的 UDP 安全链路。控制专网掉线时允许感知和只读页面继续运行，
但运动就绪检查失败，不能发送速度或姿态动作。

## 检查退出码

| 退出码 | 范围 |
|---:|---|
| `10` | 系统时间、管理/雷达网络或地图包 |
| `20` | 控制网、ACK 或急停状态 |
| `30` | Livox、FAST-LIO2、里程计或扫描 |
| `40` | ICP 定位或 TF |
| `50` | Nav2 lifecycle、地图发布者或 Action |

## systemd 模板

`systemd/` 只包含建图和导航模板。Web、UDP sender 与 PTP 分别由各自功能包维护，避免一个
服务同时拥有多条链路。安装模板使用根目录 `scripts/install.sh --services`；安装不会自动启动
建图或导航。

`run_web_bridge.sh`、`run_keyboard_teleop.sh` 和 `time_sync_start.sh` 作为可选维护工具保留，
不属于正式 Web 或安全运动主链路。
