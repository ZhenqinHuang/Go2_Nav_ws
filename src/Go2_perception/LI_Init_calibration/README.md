# LI-Init 标定使用说明

## 环境说明

- 宿主机：ROS2 Foxy（aarch64/Jetson）
- 标定容器：ROS1 Noetic（Docker）
- LI-Init 使用 CustomMsg 格式接收 MID360 数据，录 bag 时需临时切换驱动输出格式

---

## 标定流程

### 第一步：构建镜像（只需一次，约 15 分钟）

```bash
cd /home/unitree/Go2_Nav_ws/src/Go2_perception/LI_Init_calibration
sudo ./build_docker.sh
```

### 第二步：录制标定 bag（宿主机）

LI-Init 需要 CustomMsg 格式，临时修改驱动 launch 文件：

```bash
# 编辑 /home/unitree/ws_Livox/src/livox_ros_driver2/launch_ROS2/msg_MID360_launch.py
# 将 xfer_format = 0 改为 xfer_format = 1
```

启动驱动并录 bag：
```bash
cd ~/ws_Livox && source install/setup.bash
ros2 launch livox_ros_driver2 msg_MID360_launch.py &

# 新终端录制（录 60-120 秒）
ros2 bag record /livox/lidar /livox/imu -o ~/liinit_calib.bag
```

控制 GO2 做激励运动（录制期间）：
- 直线前进/后退 2-3 米，重复
- 左右平移
- 原地旋转 ±90°，重复 2-3 次

录完后把驱动 `xfer_format` 改回 `0`。

### 第三步：转换 bag 格式（ROS2 → ROS1）

```bash
pip3 install rosbags
rosbags-convert ~/liinit_calib.bag --dst ~/liinit_calib_ros1.bag
```

### 第四步：进入容器运行标定

```bash
./run_liinit.sh
```

容器内执行：
```bash
# 回放 bag
rosbag play /bags/liinit_calib_ros1.bag --clock

# 新终端启动标定
roslaunch lidar_imu_init livox_mid360.launch rviz:=false
```

等待终端输出收敛结果，形如：
```
Rotation LiDAR to IMU: [r00, r01, r02, r10, r11, r12, r20, r21, r22]
Translation LiDAR to IMU: [x, y, z]
Time offset: x.xxx s
```

### 第五步：填写标定结果

将结果填入 `/home/unitree/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml`：

```yaml
mapping:
    extrinsic_T: [ x, y, z ]
    extrinsic_R: [ r00, r01, r02,
                   r10, r11, r12,
                   r20, r21, r22 ]
    time_offset_lidar_to_imu: x.xxx
```

---

## 注意事项

- 标定环境特征要丰富，避免空旷走廊
- 激励运动要充分，平移和旋转都需要
- bag 转换需要安装 `rosbags`：`pip3 install rosbags`
- 标定结果中 Rotation 是 LiDAR→IMU，与 FAST-LIO2 的 `extrinsic_R` 定义一致
