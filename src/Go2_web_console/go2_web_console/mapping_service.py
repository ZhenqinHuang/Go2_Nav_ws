"""Lifecycle management for the operator-driven FAST-LIO mapping workflow."""

from __future__ import annotations

import asyncio
from datetime import datetime
import io
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
from typing import Optional
import zipfile


class MappingError(RuntimeError):
    """A mapping action could not be completed safely."""


class MappingManager:
    """Start, save and convert maps without replacing the active navigation map."""

    def __init__(
        self,
        *,
        maps_dir: Path = Path("/home/nvidia/Go2_Nav_ws/maps"),
        fastlio_config: Path = Path(
            "/home/nvidia/ws_fastlio2/src/FAST_LIO_ROS2/config/mid360.yaml"
        ),
        runtime_dir: Path = Path("/home/nvidia/.local/state/go2-console/mapping"),
        map_bundle_tool: Path = Path(
            "/home/nvidia/Go2_Nav_ws/scripts/map_bundle.py"
        ),
    ) -> None:
        self.maps_dir = maps_dir
        self.fastlio_config = fastlio_config
        self.runtime_dir = runtime_dir
        self.map_bundle_tool = map_bundle_tool
        self._operation_lock: Optional[asyncio.Lock] = None
        self._fastlio_process: Optional[subprocess.Popen] = None
        self._livox_process: Optional[subprocess.Popen] = None
        self._current_pcd: Optional[Path] = None
        self._started_livox = False

    def _lock(self) -> asyncio.Lock:
        # Python 3.8 binds asyncio primitives to the current loop at creation.
        # create_app() is constructed before aiohttp starts its loop, so defer it.
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

    def _fastlio_running(self) -> bool:
        return self._process_running(r"/fastlio_mapping")

    def _livox_running(self) -> bool:
        return self._process_running(r"/livox_ros_driver2_node")

    @staticmethod
    def _ros_graph_has(kind: str, name: str) -> bool:
        command = (
            "source /opt/ros/foxy/setup.bash && "
            "source /home/nvidia/unitree_ros2/install/setup.bash && "
            "source /home/nvidia/ws_Livox/install/setup.bash && "
            "source /home/nvidia/ws_fastlio2/install/setup.bash && "
            f"ros2 {kind} list"
        )
        try:
            result = subprocess.run(
                ["/bin/bash", "-lc", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5.0,
                text=True,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and name in result.stdout.splitlines()

    @staticmethod
    def _file_summary(path: Path) -> dict:
        stat = path.stat()
        return {
            "name": path.name,
            "bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        }

    def _latest_web_pcd(self) -> Optional[Path]:
        candidates = list(self.maps_dir.glob("MID360_web_*.pcd"))
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def status(self) -> dict:
        self.maps_dir.mkdir(parents=True, exist_ok=True)
        latest_pcd = self._current_pcd or self._latest_web_pcd()
        pcds = sorted(
            self.maps_dir.glob("MID360_web_*.pcd"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:8]
        maps = sorted(
            [
                path
                for path in (
                    self.maps_dir / "MID360_map.yaml",
                    *self.maps_dir.glob("MID360_web_*_map.yaml"),
                )
                if path.is_file()
            ],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:8]
        mapping_running = self._fastlio_running()
        lidar_running = self._livox_running()

        if mapping_running:
            message = "正在建图，请缓慢移动 Go2 并尽量形成闭环"
        elif latest_pcd and latest_pcd.is_file():
            message = "建图已停止，可以生成 2D 导航地图"
        elif lidar_running:
            message = "雷达在线，可以开始建图"
        else:
            message = "等待雷达连接，开始建图时会尝试启动驱动"

        return {
            "mapping_running": mapping_running,
            "mapping_owned": mapping_running and self._current_pcd is not None,
            "lidar_running": lidar_running,
            "session_pcd": self._current_pcd.name if self._current_pcd else None,
            "last_pcd": self._file_summary(latest_pcd)
            if latest_pcd and latest_pcd.is_file()
            else None,
            "message": message,
            "pointclouds": [self._file_summary(path) for path in pcds],
            "maps": [self._file_summary(path) for path in maps],
        }

    def map_bundle(self, map_name: str) -> bytes:
        """Return one Web-generated YAML/PGM map as an editor-compatible ZIP."""
        if str(map_name) != "MID360_map.yaml" and not re.fullmatch(
            r"MID360_web_[0-9]{8}_[0-9]{6}_map\.yaml", str(map_name)
        ):
            raise MappingError("地图名称无效")

        maps_root = self.maps_dir.resolve()
        yaml_path = (maps_root / str(map_name)).resolve()
        try:
            yaml_path.relative_to(maps_root)
        except ValueError as exc:
            raise MappingError("地图路径超出允许目录") from exc
        if not yaml_path.is_file():
            raise MappingError("地图文件不存在")
        if yaml_path.stat().st_size > 128 * 1024:
            raise MappingError("地图配置文件过大")

        yaml_content = yaml_path.read_text(encoding="utf-8")
        image_match = re.search(
            r"(?m)^\s*image\s*:\s*(.+?)\s*$", yaml_content
        )
        if image_match is None:
            raise MappingError("地图 YAML 缺少 image 字段")
        image_value = image_match.group(1).strip().strip("\"'")
        image_candidate = Path(image_value)
        if not image_candidate.is_absolute():
            image_candidate = yaml_path.parent / image_candidate
        image_path = image_candidate.resolve()
        try:
            image_path.relative_to(maps_root)
        except ValueError as exc:
            raise MappingError("地图图像路径超出允许目录") from exc
        if image_path.suffix.lower() != ".pgm" or not image_path.is_file():
            raise MappingError("地图对应的 PGM 文件不存在")
        if image_path.stat().st_size > 128 * 1024 * 1024:
            raise MappingError("地图图像文件过大")

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(yaml_path.name, yaml_content)
            archive.write(image_path, arcname=image_path.name)
            topology_path = yaml_path.with_suffix(".topology")
            if topology_path.is_file() and topology_path.stat().st_size <= 8 * 1024 * 1024:
                archive.write(topology_path, arcname=topology_path.name)
        return output.getvalue()

    def _write_session_config(self, destination: Path, pcd_path: Path) -> None:
        if not self.fastlio_config.is_file():
            raise MappingError(f"FAST-LIO 配置不存在：{self.fastlio_config}")
        source = self.fastlio_config.read_text(encoding="utf-8")
        replacement = f'    map_file_path: "{pcd_path}"'
        updated, count = re.subn(
            r"(?m)^\s*map_file_path\s*:.*$",
            lambda _match: replacement,
            source,
            count=1,
        )
        if count != 1:
            raise MappingError("FAST-LIO 配置缺少 map_file_path")
        destination.write_text(updated, encoding="utf-8")

    def _launch(self, command: str, log_name: str) -> subprocess.Popen:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.runtime_dir / log_name
        with log_path.open("ab", buffering=0) as log_file:
            return subprocess.Popen(
                ["/bin/bash", "-lc", command],
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

    async def _wait_for(self, predicate, *, timeout: float, error: str) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if await loop.run_in_executor(None, predicate):
                return
            await asyncio.sleep(0.5)
        raise MappingError(error)

    @staticmethod
    async def _run_ros(command: str, *, timeout: float = 30.0) -> str:
        process = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "-lc",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise MappingError("ROS 操作超时") from exc
        text = output.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            tail = text[-500:] if text else "没有返回详细信息"
            raise MappingError(f"ROS 操作失败：{tail}")
        return text

    @staticmethod
    def _stop_process_group(process: Optional[subprocess.Popen]) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGINT)
        except (ProcessLookupError, PermissionError):
            return

    async def _cleanup_failed_start(self) -> None:
        self._stop_process_group(self._fastlio_process)
        if self._started_livox:
            self._stop_process_group(self._livox_process)
        await asyncio.sleep(1.0)
        self._fastlio_process = None
        self._livox_process = None
        self._started_livox = False

    async def start(self, *, nav_active: bool = False) -> dict:
        async with self._lock():
            if nav_active:
                raise MappingError("Nav2 正在执行任务，请先取消导航")
            if self._fastlio_running():
                raise MappingError("检测到 FAST-LIO 已运行，请先停止现有定位或建图进程")

            self.maps_dir.mkdir(parents=True, exist_ok=True)
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pcd_path = self.maps_dir / f"MID360_web_{stamp}.pcd"
            config_path = self.runtime_dir / f"mid360_web_{stamp}.yaml"
            self._write_session_config(config_path, pcd_path)
            self._current_pcd = pcd_path
            self._started_livox = False

            try:
                if not self._livox_running():
                    self._livox_process = self._launch(
                        "source /opt/ros/foxy/setup.bash && "
                        "source /home/nvidia/ws_Livox/install/setup.bash && "
                        "exec ros2 launch livox_ros_driver2 msg_MID360s_launch.py",
                        f"livox_{stamp}.log",
                    )
                    self._started_livox = True
                    await self._wait_for(
                        self._livox_running,
                        timeout=15.0,
                        error="MID360S 驱动启动失败，请检查雷达供电和 eth1 网络",
                    )

                await self._wait_for(
                    lambda: self._ros_graph_has("topic", "/livox/lidar"),
                    timeout=20.0,
                    error="雷达进程已运行，但 /livox/lidar 没有出现在 ROS 网络中",
                )

                self._fastlio_process = self._launch(
                    "source /opt/ros/foxy/setup.bash && "
                    "source /home/nvidia/unitree_ros2/install/setup.bash && "
                    "source /home/nvidia/ws_Livox/install/setup.bash && "
                    "source /home/nvidia/ws_fastlio2/install/setup.bash && "
                    "exec ros2 launch fast_lio mapping.launch.py "
                    f"config_path:={config_path.parent} "
                    f"config_file:={config_path.name} rviz:=false",
                    f"fastlio_{stamp}.log",
                )
                await self._wait_for(
                    self._fastlio_running,
                    timeout=15.0,
                    error="FAST-LIO2 启动失败",
                )
                await self._wait_for(
                    lambda: self._ros_graph_has("service", "/map_save"),
                    timeout=20.0,
                    error="FAST-LIO2 已启动，但地图保存服务未就绪",
                )
            except Exception:
                await self._cleanup_failed_start()
                raise

            return self.status()

    async def stop_and_save(self) -> dict:
        async with self._lock():
            if not self._fastlio_running():
                raise MappingError("当前没有正在运行的建图任务")
            if self._current_pcd is None:
                raise MappingError("当前建图任务不是由网页启动，不能确定安全的保存路径")

            output = await self._run_ros(
                "source /opt/ros/foxy/setup.bash && "
                "source /home/nvidia/ws_fastlio2/install/setup.bash && "
                "ros2 service call /map_save std_srvs/srv/Trigger '{}'",
                timeout=120.0,
            )
            if "success=true" not in output.replace(" ", "").lower():
                raise MappingError(f"FAST-LIO2 未确认地图保存成功：{output[-300:]}")

            await self._wait_for(
                lambda: self._current_pcd is not None
                and self._current_pcd.is_file()
                and self._current_pcd.stat().st_size >= 1024,
                timeout=30.0,
                error="未生成有效 PCD，请确认建图时 /cloud_registered 持续有数据",
            )

            self._stop_process_group(self._fastlio_process)
            await asyncio.sleep(2.0)
            if self._fastlio_running():
                subprocess.run(
                    ["pkill", "-INT", "-f", r"/fastlio_mapping"],
                    check=False,
                )
                await asyncio.sleep(1.0)
            self._fastlio_process = None
            return self.status()

    async def convert_latest(self) -> dict:
        async with self._lock():
            if self._fastlio_running():
                raise MappingError("请先点击“停止并保存”，再生成 2D 地图")
            pcd_path = self._current_pcd or self._latest_web_pcd()
            if pcd_path is None or not pcd_path.is_file():
                raise MappingError("没有可转换的网页建图 PCD")
            bundle_id = pcd_path.stem
            staging = self.runtime_dir / "map-staging" / bundle_id
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir(parents=True)
            shutil.copy2(pcd_path, staging / "MID360.pcd")
            output_prefix = staging / "MID360_map"
            await self._run_ros(
                "source /opt/ros/foxy/setup.bash && "
                "source /home/nvidia/Go2_Nav_ws/install/setup.bash && "
                "ros2 launch pcd_to_map pcd_to_map.launch.py "
                f"pcd_file:={pcd_path} output_path:={output_prefix}",
                timeout=300.0,
            )
            pgm_path = output_prefix.with_suffix(".pgm")
            yaml_path = output_prefix.with_suffix(".yaml")
            if not pgm_path.is_file() or not yaml_path.is_file():
                raise MappingError("2D 转换完成，但没有生成完整的 PGM/YAML 文件")
            yaml_text = yaml_path.read_text(encoding="utf-8")
            yaml_text, count = re.subn(
                r"(?m)^\s*image\s*:.*$",
                "image: MID360_map.pgm",
                yaml_text,
                count=1,
            )
            if count != 1:
                raise MappingError("2D 地图 YAML 缺少 image 字段")
            yaml_path.write_text(yaml_text, encoding="utf-8")
            await self._run_map_bundle_tool(
                "create-manifest", str(staging), "--bundle-id", bundle_id
            )
            await self._run_map_bundle_tool(
                "promote",
                str(staging),
                str(self.maps_dir),
                "--archive",
                str(self.maps_dir / "archive"),
            )
            return self.status()

    async def _run_map_bundle_tool(self, *arguments: str) -> str:
        if not self.map_bundle_tool.is_file():
            raise MappingError(f"地图包工具不存在：{self.map_bundle_tool}")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(self.map_bundle_tool),
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()
        text = output.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            raise MappingError(f"地图包发布失败：{text[-500:]}")
        return text
