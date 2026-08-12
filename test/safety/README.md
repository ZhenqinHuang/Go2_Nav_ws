# 安全测试

安全测试保留在各自功能包中，避免复制协议、Web 和 ROS 测试代码。仓库根目录执行：

```bash
python3 -m pytest -q src/Go2_control_gateway/test
python3 -m pytest -q src/Go2_web_console/test
```

内载 C++ 网关测试按 `src/Go2_control_gateway/README.md` 构建后使用 `ctest` 执行。以上测试不得连接实机发送非零速度或姿态命令。
