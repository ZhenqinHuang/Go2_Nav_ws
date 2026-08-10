"""Lifecycle management for FAST-LIO localization and Nav2."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
from typing import Optional


class NavigationError(RuntimeError):
    """The localization or Nav2 stack could not be operated safely."""


class NavigationManager:
    """Own only the localization/Nav2 processes started by the Web console.

    Livox and the UDP motion sender are long-running services on the Jetson.  This
    manager verifies them as prerequisites, but deliberately never starts, stops,
    or kills either one.
    """

    PROCESS_ORDER = ("fastlio", "odom_bridge", "localization", "pc2scan", "nav2")
    CHECK_ORDER = (
        "livox",
        "motion_gateway",
        "cloud_registered",
        "odom",
        "scan",
        "tf",
        "nav2_lifecycle",
        "navigate_to_pose",
        "initial_pose",
    )
    CHECK_LABELS = {
        "livox": "Livox MID360S",
        "motion_gateway": "运动网关",
        "cloud_registered": "/cloud_registered",
        "odom": "/odom",
        "scan": "/scan",
        "tf": "TF map → odom → base_link",
        "nav2_lifecycle": "Nav2 lifecycle",
        "navigate_to_pose": "/navigate_to_pose action",
        "initial_pose": "人工重定位",
    }
    # Keep navigation speed controls aligned with the manual-control panel and
    # the cmd_vel bridge.  Go2 is a quadruped: commands below its gait-start
    # threshold can leave DWB believing it is accelerating while it stays put.
    DEFAULT_LINEAR_SPEED = 0.25
    DEFAULT_ANGULAR_SPEED = 0.60
    MIN_LINEAR_SPEED = 0.05
    MAX_LINEAR_SPEED = 0.60
    MIN_ANGULAR_SPEED = 0.10
    MAX_ANGULAR_SPEED = 1.40
    EXTERNAL_PROCESS_PATTERNS = {
        "FAST-LIO": r"/laser_mapping",
        "FAST-LIO Web": r"/fastlio_mapping",
        "里程计桥": r"odom_tf_bridge_node",
        "定位地图发布": r"/pcd_publisher",
        "全局定位": r"/global_localization",
        "定位 TF 融合": r"/transform_fusion",
        "点云过滤": r"/cloud_filter_node",
        "LaserScan 转换": r"/pointcloud_to_laserscan_node",
        "Nav2 map_server": r"/nav2_map_server/map_server",
        "Nav2 planner_server": r"/nav2_planner/planner_server",
        "Nav2 controller_server": r"/nav2_controller/controller_server",
        "Nav2 bt_navigator": r"/nav2_bt_navigator/bt_navigator",
        "Nav2 lifecycle manager": r"/nav2_lifecycle_manager/lifecycle_manager",
    }

    def __init__(
        self,
        *,
        maps_dir: Path = Path("/home/nvidia/Go2_Nav_ws/maps"),
        fastlio_config: Path = Path(
            "/home/nvidia/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml"
        ),
        controller_config: Path = Path(
            "/home/nvidia/Go2_Nav_ws/install/go2_nav2/share/"
            "go2_nav2/config/controller_server.yaml"
        ),
        runtime_dir: Path = Path("/home/nvidia/.local/state/go2-console/navigation"),
        speed_file: Optional[Path] = None,
    ) -> None:
        self.maps_dir = maps_dir
        self.fastlio_config = fastlio_config
        self.controller_config = controller_config
        self.runtime_dir = runtime_dir
        self.speed_file = speed_file or (runtime_dir / "speed.json")
        self._operation_lock: Optional[asyncio.Lock] = None
        self._processes: dict[str, subprocess.Popen] = {}
        self._phase = "idle"
        self._selected_map: Optional[Path] = None
        self._selected_pcd: Optional[Path] = None
        self._last_error: Optional[str] = None
        self._checks = {name: False for name in self.CHECK_ORDER}
        self._localized = False
        self._speed = self._load_speed()

    @classmethod
    def _validated_speed(cls, linear: float, angular: float) -> dict[str, float]:
        try:
            linear = float(linear)
            angular = float(angular)
        except (TypeError, ValueError) as exc:
            raise NavigationError("导航速度必须是数值") from exc
        if not math.isfinite(linear) or not math.isfinite(angular):
            raise NavigationError("导航速度必须是有限数值")
        if not cls.MIN_LINEAR_SPEED <= linear <= cls.MAX_LINEAR_SPEED:
            raise NavigationError(
                f"前进速度必须在 {cls.MIN_LINEAR_SPEED:.2f}–{cls.MAX_LINEAR_SPEED:.2f} m/s"
            )
        if not cls.MIN_ANGULAR_SPEED <= angular <= cls.MAX_ANGULAR_SPEED:
            raise NavigationError(
                f"转向速度必须在 {cls.MIN_ANGULAR_SPEED:.2f}–{cls.MAX_ANGULAR_SPEED:.2f} rad/s"
            )
        return {"linear": round(linear, 3), "angular": round(angular, 3)}

    def _load_speed(self) -> dict[str, float]:
        try:
            data = json.loads(self.speed_file.read_text(encoding="utf-8"))
            return self._validated_speed(data["linear"], data["angular"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, NavigationError):
            return {
                "linear": self.DEFAULT_LINEAR_SPEED,
                "angular": self.DEFAULT_ANGULAR_SPEED,
            }

    def _persist_speed(self) -> None:
        self.speed_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.speed_file.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._speed, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.speed_file)

    def speed(self) -> dict:
        return {
            **self._speed,
            "limits": {
                "linear_min": self.MIN_LINEAR_SPEED,
                "linear_max": self.MAX_LINEAR_SPEED,
                "angular_min": self.MIN_ANGULAR_SPEED,
                "angular_max": self.MAX_ANGULAR_SPEED,
            },
        }

    async def set_speed(self, linear: float, angular: float) -> dict:
        async with self._lock():
            if self._processes:
                raise NavigationError("请先停止定位与导航系统，再调整导航速度")
            self._speed = self._validated_speed(linear, angular)
            self._persist_speed()
            return self.speed()

    def _lock(self) -> asyncio.Lock:
        if self._operation_lock is None:
            self._operation_lock = asyncio.Lock()
        return self._operation_lock

    @staticmethod
    def _process_running(pattern: str) -> bool:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0

    def _livox_running(self) -> bool:
        return self._process_running(r"/livox_ros_driver2_node")

    @staticmethod
    def _motion_gateway_active() -> bool:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", "go2-motion-sender.service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0

    def _external_processes(self) -> list[str]:
        if self._processes:
            return []
        return [
            label
            for label, pattern in self.EXTERNAL_PROCESS_PATTERNS.items()
            if self._process_running(pattern)
        ]

    @staticmethod
    def _ros_prefix() -> str:
        return (
            "source /opt/ros/foxy/setup.bash && "
            "source /home/nvidia/unitree_ros2/install/setup.bash && "
            "source /home/nvidia/ws_Livox/install/setup.bash && "
            "source /home/nvidia/ws_fastlio2/install/setup.bash && "
            "source /home/nvidia/Go2_Nav_ws/install/setup.bash"
        )

    @classmethod
    def _run_ros_check(cls, command: str, *, timeout: float = 8.0) -> bool:
        try:
            result = subprocess.run(
                ["/bin/bash", "-lc", f"{cls._ros_prefix()} && {command}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=timeout,
                text=True,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    @classmethod
    def _ros_graph_has(cls, kind: str, name: str) -> bool:
        quoted = shlex.quote(name)
        return cls._run_ros_check(
            f"ros2 {kind} list | grep -Fxq -- {quoted}", timeout=6.0
        )

    @classmethod
    def _tf_available(cls) -> bool:
        return cls._run_ros_check(
            "timeout 5s ros2 run tf2_ros tf2_echo map base_link "
            "2>/dev/null | grep -qi translation",
            timeout=7.0,
        )

    @classmethod
    def _nav2_lifecycle_active(cls) -> bool:
        nodes = (
            "/map_server",
            "/planner_server",
            "/controller_server",
            "/recoveries_server",
            "/bt_navigator",
            "/waypoint_follower",
        )
        quoted_nodes = " ".join(shlex.quote(node) for node in nodes)
        return cls._run_ros_check(
            "for node in "
            f"{quoted_nodes}; do "
            "ros2 lifecycle get \"$node\" 2>/dev/null | grep -qi 'active' || exit 1; "
            "done",
            timeout=18.0,
        )

    @classmethod
    def _navigate_action_available(cls) -> bool:
        return cls._ros_graph_has("action", "/navigate_to_pose")

    def _write_controller_config(self) -> Path:
        try:
            rendered = self.controller_config.read_text(encoding="utf-8")
        except OSError as exc:
            raise NavigationError(
                f"Nav2 控制器配置不可读：{self.controller_config}"
            ) from exc
        replacements = {
            "max_vel_x": self._speed["linear"],
            "max_speed_xy": self._speed["linear"],
            "max_vel_theta": self._speed["angular"],
            "acc_lim_x": 1.2,
            "decel_lim_x": -1.5,
            "acc_lim_theta": 2.5,
            "decel_lim_theta": -2.5,
        }
        for name, value in replacements.items():
            pattern = rf"^(\s*{re.escape(name)}:\s*).*$"
            rendered, count = re.subn(
                pattern,
                lambda match, replacement=value: f"{match.group(1)}{replacement}",
                rendered,
                count=1,
                flags=re.MULTILINE,
            )
            if count != 1:
                raise NavigationError(f"Nav2 控制器配置缺少参数：{name}")
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        target = self.runtime_dir / "controller_server.web.yaml"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(target)
        return target

    def _resolve_map_pair(self, map_name: str) -> tuple[Path, Path]:
        if not re.fullmatch(
            r"MID360_web_[0-9]{8}_[0-9]{6}_map\.yaml", str(map_name)
        ):
            raise NavigationError("请选择一张 Web 生成的地图")

        maps_root = self.maps_dir.resolve()
        yaml_path = (maps_root / str(map_name)).resolve()
        pcd_name = str(map_name)[: -len("_map.yaml")] + ".pcd"
        pcd_path = (maps_root / pcd_name).resolve()
        for path in (yaml_path, pcd_path):
            try:
                path.relative_to(maps_root)
            except ValueError as exc:
                raise NavigationError("地图路径超出允许目录") from exc
            if not path.is_file() or path.stat().st_size <= 0:
                raise NavigationError(f"地图配对文件不存在：{path.name}")

        if yaml_path.stat().st_size > 128 * 1024:
            raise NavigationError("地图 YAML 文件过大")
        yaml_content = yaml_path.read_text(encoding="utf-8")
        image_match = re.search(r"(?m)^\s*image\s*:\s*(.+?)\s*$", yaml_content)
        if image_match is None:
            raise NavigationError("地图 YAML 缺少 image 字段")
        image_value = image_match.group(1).strip().strip("\"'")
        image_path = Path(image_value)
        if not image_path.is_absolute():
            image_path = yaml_path.parent / image_path
        image_path = image_path.resolve()
        try:
            image_path.relative_to(maps_root)
        except ValueError as exc:
            raise NavigationError("地图图像路径超出允许目录") from exc
        if image_path.suffix.lower() != ".pgm" or not image_path.is_file():
            raise NavigationError("地图对应的 PGM 文件不存在")
        return yaml_path, pcd_path

    def available_maps(self) -> list[dict]:
        self.maps_dir.mkdir(parents=True, exist_ok=True)
        pairs = []
        candidates = sorted(
            self.maps_dir.glob("MID360_web_*_map.yaml"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for yaml_path in candidates:
            try:
                resolved_yaml, pcd_path = self._resolve_map_pair(yaml_path.name)
            except NavigationError:
                continue
            pairs.append(
                {
                    "map_name": resolved_yaml.name,
                    "pcd_name": pcd_path.name,
                    "modified": datetime.fromtimestamp(
                        max(resolved_yaml.stat().st_mtime, pcd_path.stat().st_mtime)
                    ).isoformat(timespec="seconds"),
                }
            )
        return pairs

    def _launch(self, name: str, command: str, stamp: str) -> subprocess.Popen:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.runtime_dir / f"{stamp}_{name}.log"
        with log_path.open("ab", buffering=0) as log_file:
            process = subprocess.Popen(
                ["/bin/bash", "-lc", command],
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self._processes[name] = process
        return process

    async def _wait_for(
        self,
        predicate,
        *,
        timeout: float,
        error: str,
        interval: float = 0.5,
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if await loop.run_in_executor(None, predicate):
                return
            await asyncio.sleep(interval)
        raise NavigationError(error)

    def _command(self, ros_command: str) -> str:
        return f"{self._ros_prefix()} && exec {ros_command}"

    async def start(self, map_name: str) -> dict:
        async with self._lock():
            if self._processes:
                raise NavigationError("定位与导航系统已启动，请勿重复启动")
            yaml_path, pcd_path = self._resolve_map_pair(map_name)
            if not self.fastlio_config.is_file():
                raise NavigationError(f"FAST-LIO 配置不存在：{self.fastlio_config}")
            if not self._livox_running():
                raise NavigationError("Livox MID360S 未运行，请先恢复雷达驱动")
            if not self._motion_gateway_active():
                raise NavigationError(
                    "go2-motion-sender.service 未运行，请先恢复运动网关"
                )
            conflicts = self._external_processes()
            if conflicts:
                raise NavigationError(
                    "检测到非 Web 管理的定位/Nav2 进程：" + "、".join(conflicts)
                )

            self._selected_map = yaml_path
            self._selected_pcd = pcd_path
            self._last_error = None
            self._phase = "starting"
            self._localized = False
            self._checks = {name: False for name in self.CHECK_ORDER}
            self._checks["livox"] = True
            self._checks["motion_gateway"] = True
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            fastlio_config_dir = shlex.quote(str(self.fastlio_config.parent))
            fastlio_config_name = shlex.quote(self.fastlio_config.name)
            controller_config = self._write_controller_config()
            try:
                self._launch(
                    "fastlio",
                    self._command(
                        "ros2 launch fast_lio mapping.launch.py "
                        f"config_path:={fastlio_config_dir} "
                        f"config_file:={fastlio_config_name} rviz:=false"
                    ),
                    stamp,
                )
                await self._wait_for(
                    lambda: self._ros_graph_has("topic", "/cloud_registered"),
                    timeout=30.0,
                    error="FAST-LIO 已启动，但 /cloud_registered 未就绪",
                )
                await self._wait_for(
                    lambda: self._ros_graph_has("topic", "/cloud_registered_body"),
                    timeout=15.0,
                    error="FAST-LIO 缺少 /cloud_registered_body",
                )
                self._checks["cloud_registered"] = True

                self._launch(
                    "odom_bridge",
                    self._command(
                        "ros2 launch odom_tf_bridge odom_bridge.launch.py "
                        "base_frame:=base_link"
                    ),
                    stamp,
                )
                await self._wait_for(
                    lambda: self._ros_graph_has("topic", "/odom"),
                    timeout=20.0,
                    error="里程计桥已启动，但 /odom 未就绪",
                )
                self._checks["odom"] = True

                self._launch(
                    "localization",
                    self._command(
                        "ros2 launch fast_lio_localization_ros2 "
                        "localize_go2.launch.py "
                        f"map:={shlex.quote(str(pcd_path))} rviz:=false"
                    ),
                    stamp,
                )
                await self._wait_for(
                    lambda: self._ros_graph_has("topic", "/map_to_odom"),
                    timeout=40.0,
                    error="FAST-LIO 定位已启动，但 /map_to_odom 未就绪",
                )

                self._launch(
                    "pc2scan",
                    self._command("ros2 launch go2_pc2scan pc2scan.launch.py"),
                    stamp,
                )
                await self._wait_for(
                    lambda: self._ros_graph_has("topic", "/scan"),
                    timeout=20.0,
                    error="点云转 LaserScan 已启动，但 /scan 未就绪",
                )
                self._checks["scan"] = True
                await self._wait_for(
                    self._tf_available,
                    timeout=30.0,
                    error="TF 链 map → odom → base_link 未就绪",
                    interval=1.0,
                )
                self._checks["tf"] = True

                self._launch(
                    "nav2",
                    self._command(
                        "ros2 launch go2_nav2 nav2_bringup.launch.py "
                        f"map:={shlex.quote(str(yaml_path))} "
                        "use_sim_time:=false use_rviz:=false controller:=dwb "
                        "controller_params_file:="
                        f"{shlex.quote(str(controller_config))}"
                    ),
                    stamp,
                )
                await self._wait_for(
                    self._nav2_lifecycle_active,
                    timeout=60.0,
                    error="Nav2 节点已启动，但 lifecycle 未全部进入 active",
                    interval=1.0,
                )
                self._checks["nav2_lifecycle"] = True
                await self._wait_for(
                    self._navigate_action_available,
                    timeout=20.0,
                    error="Nav2 已激活，但 /navigate_to_pose action 不可用",
                    interval=1.0,
                )
                self._checks["navigate_to_pose"] = True
                self._phase = "awaiting_localization"
                return self.status()
            except Exception as exc:
                await self._terminate_owned()
                self._phase = "error"
                self._last_error = str(exc)
                if isinstance(exc, NavigationError):
                    raise
                raise NavigationError(f"启动定位与导航失败：{exc}") from exc

    @staticmethod
    def _signal_process_group(process: subprocess.Popen, sig: int) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError):
            return

    async def _terminate_owned(self) -> None:
        processes = [
            self._processes[name]
            for name in reversed(self.PROCESS_ORDER)
            if name in self._processes
        ]
        for process in processes:
            self._signal_process_group(process, signal.SIGINT)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 5.0
        while loop.time() < deadline and any(
            process.poll() is None for process in processes
        ):
            await asyncio.sleep(0.2)
        for process in processes:
            self._signal_process_group(process, signal.SIGKILL)
        self._processes.clear()

    async def stop(self) -> dict:
        async with self._lock():
            self._phase = "stopping"
            await self._terminate_owned()
            self._phase = "idle"
            self._last_error = None
            self._localized = False
            self._checks = {name: False for name in self.CHECK_ORDER}
            self._checks["livox"] = self._livox_running()
            self._checks["motion_gateway"] = self._motion_gateway_active()
            return self.status()

    def require_stack_ready(self) -> None:
        status = self.status()
        if status["stack_ready"]:
            return
        raise NavigationError(f"定位与 Nav2 尚未完成启动：{status['message']}")

    def mark_localized(self) -> dict:
        self.require_stack_ready()
        self._localized = True
        self._checks["initial_pose"] = True
        self._phase = "ready"
        return self.status()

    def require_ready(self) -> None:
        status = self.status()
        if status["ready"]:
            return
        missing = [
            self.CHECK_LABELS[name]
            for name in self.CHECK_ORDER
            if not status["checks"].get(name, False)
        ]
        detail = "、".join(missing) if missing else status["message"]
        raise NavigationError(f"定位与导航系统未就绪：{detail}")

    def status(self) -> dict:
        self._checks["livox"] = self._livox_running()
        self._checks["motion_gateway"] = self._motion_gateway_active()
        dead = [
            name
            for name, process in self._processes.items()
            if process.poll() is not None
        ]
        if dead and self._phase in {"starting", "awaiting_localization", "ready"}:
            self._phase = "error"
            self._last_error = "进程异常退出：" + "、".join(dead)
        process_state = {
            name: bool(
                name in self._processes and self._processes[name].poll() is None
            )
            for name in self.PROCESS_ORDER
        }
        running = any(process_state.values())
        stack_checks = all(
            value for name, value in self._checks.items() if name != "initial_pose"
        )
        stack_ready = (
            self._phase in {"awaiting_localization", "ready"}
            and stack_checks
            and all(process_state.values())
        )
        ready = stack_ready and self._localized and self._checks["initial_pose"]
        if ready:
            message = "重定位已确认，可以发送导航目标"
        elif stack_ready:
            message = "定位与 Nav2 已启动，请先在地图上执行人工重定位"
        elif self._phase == "starting":
            message = "正在启动定位与 Nav2，请等待就绪检查"
        elif self._phase == "stopping":
            message = "正在停止定位与 Nav2"
        elif self._last_error:
            message = self._last_error
        else:
            message = "请选择配对地图并启动定位与导航"
        return {
            "phase": self._phase,
            "running": running,
            "ready": ready,
            "stack_ready": stack_ready,
            "localized": self._localized,
            "selected_map": self._selected_map.name if self._selected_map else None,
            "selected_pcd": self._selected_pcd.name if self._selected_pcd else None,
            "checks": dict(self._checks),
            "processes": process_state,
            "available_maps": self.available_maps(),
            "speed": self.speed(),
            "message": message,
            "last_error": self._last_error,
        }
