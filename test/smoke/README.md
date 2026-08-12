# 冒烟测试

本目录是零运动冒烟验证入口。先运行不接管底盘的仓库检查：

```bash
python3 -m pytest -q test/interface
python3 -m pytest -q src/Go2_control_gateway/test/test_smoke_test_core.py
bash scripts/check_system.sh
```

Jetson 上的联网检查只验证路由、地图、ROS topic/TF、Nav2 lifecycle 和 UDP ACK。未经现场授权，不发送非零速度，不执行站立或趴下。
