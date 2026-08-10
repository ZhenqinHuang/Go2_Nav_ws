"""Authenticated aiohttp backend for the trusted-LAN Go2 console."""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
import inspect
import json
import math
import os
from pathlib import Path
import time
from typing import Callable, Optional

from aiohttp import ClientSession, WSMsgType, web

from .console_core import (
    AuthenticationError,
    ConsolePolicy,
    ConsolePolicyConfig,
    ControlLeaseError,
    ManualControlError,
)
from .readonly_rosbridge import RosbridgePolicyError, filter_client_message
from .mapping_service import MappingError, MappingManager
from .navigation_service import NavigationError, NavigationManager


class CsrfError(PermissionError):
    pass


@dataclass(frozen=True)
class ConsoleServerConfig:
    bind_ip: str = "192.168.0.101"
    port: int = 8080
    cookie_name: str = "go2_session"
    api_rate_limit: int = 60
    api_rate_window_sec: float = 1.0
    max_request_body_bytes: int = 16 * 1024
    watchdog_interval_sec: float = 0.05
    websocket_state_interval_sec: float = 0.25
    rosbridge_url: str = "ws://127.0.0.1:9090"
    rosbridge_max_message_bytes: int = 32 * 1024 * 1024


class RateLimiter:
    def __init__(
        self,
        *,
        limit: int,
        window_sec: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = max(1, int(limit))
        self.window_sec = float(window_sec)
        self._clock = clock
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self._clock()
        requests = self._requests[key]
        while requests and now - requests[0] >= self.window_sec:
            requests.popleft()
        if len(requests) >= self.limit:
            return False
        requests.append(now)
        return True


async def _invoke(method, *args):
    if inspect.iscoroutinefunction(method):
        return await method(*args)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, method, *args)
    if inspect.isawaitable(result):
        return await result
    return result


class ConsoleController:
    def __init__(self, policy: ConsolePolicy, ros_adapter) -> None:
        self.policy = policy
        self.ros_adapter = ros_adapter
        self._last_sent_manual = (0.0, 0.0, 0.0)

    async def state(self) -> dict:
        ros_state = await _invoke(self.ros_adapter.get_state)
        self._sync_nav_policy(ros_state)
        return {**ros_state, **self.policy.public_state()}

    async def stand_up(self, session_id: str) -> bool:
        self.policy.authorize_control_action(session_id)
        await self.force_stop()
        return bool(await _invoke(self.ros_adapter.stand_up))

    async def stand_down(self, session_id: str) -> bool:
        self.policy.authorize_control_action(session_id)
        await self.force_stop()
        return bool(await _invoke(self.ros_adapter.stand_down))

    async def recovery_stand(self, session_id: str) -> bool:
        self.policy.authorize_control_action(session_id)
        await self.force_stop()
        return bool(await _invoke(self.ros_adapter.recovery_stand))

    async def emergency_stop(self, session_id: str) -> bool:
        self.policy.authorize_stop_action(session_id)
        await self.force_stop()
        return bool(await _invoke(self.ros_adapter.emergency_stop))

    async def manual(
        self, session_id: str, vx: float, vy: float, vyaw: float
    ) -> bool:
        ros_state = await _invoke(self.ros_adapter.get_state)
        self._sync_nav_policy(ros_state)
        self.policy.submit_manual(session_id, vx, vy, vyaw)
        command = self.policy.current_manual_command()
        result = bool(await _invoke(self.ros_adapter.manual_command, *command))
        self._last_sent_manual = command
        return result

    async def cancel_navigation(self, session_id: str) -> bool:
        self.policy.heartbeat(session_id)
        result = bool(await _invoke(self.ros_adapter.cancel_navigation))
        if result:
            self.policy.set_nav_active(False)
        return result

    async def navigate_to_pose(
        self, session_id: str, x: float, y: float, yaw: float
    ) -> bool:
        self.policy.heartbeat(session_id)
        result = bool(
            await _invoke(self.ros_adapter.navigate_to_pose, x, y, yaw)
        )
        if result:
            self.policy.set_nav_active(True)
        return result

    async def navigate_through_poses(
        self, session_id: str, poses: list[dict[str, float]]
    ) -> bool:
        self.policy.heartbeat(session_id)
        result = bool(
            await _invoke(self.ros_adapter.navigate_through_poses, poses)
        )
        if result:
            self.policy.set_nav_active(True)
        return result

    async def set_initial_pose(
        self, session_id: str, x: float, y: float, yaw: float
    ) -> bool:
        self.policy.heartbeat(session_id)
        return bool(
            await _invoke(self.ros_adapter.set_initial_pose, x, y, yaw)
        )

    async def release(self, session_id: str, *, logout: bool = False) -> None:
        if logout:
            self.policy.logout(session_id)
        else:
            self.policy.release_control(session_id)
        await self.force_stop()

    async def disconnect(self, session_id: str) -> None:
        self.policy.disconnect(session_id)
        await self.force_stop()

    async def force_stop(self) -> None:
        await _invoke(self.ros_adapter.manual_command, 0.0, 0.0, 0.0)
        self._last_sent_manual = (0.0, 0.0, 0.0)

    async def watchdog_once(self) -> None:
        command = self.policy.current_manual_command()
        if command != self._last_sent_manual:
            await _invoke(self.ros_adapter.manual_command, *command)
            self._last_sent_manual = command

    def _sync_nav_policy(self, state: dict) -> None:
        value = str(state.get("nav2_status", "IDLE")).upper()
        self.policy.set_nav_active(
            value in {"ACCEPTED", "EXECUTING", "CANCELING", "ACTIVE"}
        )


CONSOLE_CONTROLLER_KEY = web.AppKey("console_controller", ConsoleController)
CONSOLE_POLICY_KEY = web.AppKey("console_policy", ConsolePolicy)
CONSOLE_CONFIG_KEY = web.AppKey("console_config", ConsoleServerConfig)
MAPPING_MANAGER_KEY = web.AppKey("mapping_manager", MappingManager)
NAVIGATION_MANAGER_KEY = web.AppKey("navigation_manager", NavigationManager)


def create_app(
    *,
    policy: ConsolePolicy,
    ros_adapter,
    config: Optional[ConsoleServerConfig] = None,
    web_dir: Optional[Path] = None,
    mapping_manager: Optional[MappingManager] = None,
    navigation_manager: Optional[NavigationManager] = None,
) -> web.Application:
    config = config or ConsoleServerConfig()
    controller = ConsoleController(policy, ros_adapter)
    rate_limiter = RateLimiter(
        limit=config.api_rate_limit,
        window_sec=config.api_rate_window_sec,
        clock=policy._clock,
    )

    @web.middleware
    async def error_middleware(request, handler):
        try:
            return await handler(request)
        except AuthenticationError as exc:
            return web.json_response({"error": str(exc)}, status=401)
        except CsrfError as exc:
            return web.json_response({"error": str(exc)}, status=403)
        except (
            ControlLeaseError,
            ManualControlError,
            MappingError,
            NavigationError,
        ) as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return web.json_response({"error": f"invalid request: {exc}"}, status=400)

    @web.middleware
    async def rate_limit_middleware(request, handler):
        if request.path.startswith("/api/"):
            peer = request.remote or "unknown"
            if not rate_limiter.allow(peer):
                return web.json_response({"error": "rate limit exceeded"}, status=429)
        return await handler(request)

    @web.middleware
    async def security_headers_middleware(request, handler):
        response = await handler(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers[
            "Content-Security-Policy"
        ] = "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'"
        return response

    app = web.Application(
        middlewares=[
            error_middleware,
            rate_limit_middleware,
            security_headers_middleware,
        ],
        client_max_size=config.max_request_body_bytes,
    )
    app[CONSOLE_CONTROLLER_KEY] = controller
    app[CONSOLE_POLICY_KEY] = policy
    app[CONSOLE_CONFIG_KEY] = config
    mapping_manager = mapping_manager or MappingManager()
    app[MAPPING_MANAGER_KEY] = mapping_manager
    navigation_manager = navigation_manager or NavigationManager()
    app[NAVIGATION_MANAGER_KEY] = navigation_manager

    def authenticated_session(request) -> str:
        session_id = request.cookies.get(config.cookie_name, "")
        policy.authenticate(session_id)
        return session_id

    def protected_session(request) -> str:
        session_id = authenticated_session(request)
        candidate = request.headers.get("X-CSRF-Token", "")
        if not policy.csrf_matches(session_id, candidate):
            raise CsrfError("valid CSRF token required")
        return session_id

    async def parse_json(request) -> dict:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def parse_pose(data: dict) -> tuple[float, float, float]:
        values = (
            float(data.get("x", 0.0)),
            float(data.get("y", 0.0)),
            float(data.get("yaw", 0.0)),
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("pose values must be finite")
        x, y, yaw = values
        if abs(x) > 10000.0 or abs(y) > 10000.0:
            raise ValueError("pose position is out of range")
        if abs(yaw) > math.pi:
            raise ValueError("pose yaw must be within [-pi, pi]")
        return values

    async def login(request):
        data = await parse_json(request)
        result = policy.login(
            str(data.get("username", "")),
            str(data.get("password", "")),
        )
        response = web.json_response(
            {"ok": True, "csrf_token": result.csrf_token}
        )
        response.set_cookie(
            config.cookie_name,
            result.session_id,
            httponly=True,
            secure=False,
            samesite="Strict",
            path="/",
            max_age=int(policy.config.session_idle_timeout_sec),
        )
        return response

    async def logout(request):
        session_id = protected_session(request)
        await controller.release(session_id, logout=True)
        response = web.json_response({"ok": True})
        response.del_cookie(config.cookie_name, path="/")
        return response

    async def state(request):
        authenticated_session(request)
        return web.json_response(await controller.state())

    async def acquire_control(request):
        session_id = protected_session(request)
        policy.acquire_control(session_id)
        return web.json_response({"ok": True})

    async def release_control(request):
        session_id = protected_session(request)
        await controller.release(session_id)
        return web.json_response({"ok": True})

    async def manual(request):
        session_id = protected_session(request)
        data = await parse_json(request)
        success = await controller.manual(
            session_id,
            float(data.get("vx", 0.0)),
            float(data.get("vy", 0.0)),
            float(data.get("vyaw", 0.0)),
        )
        return web.json_response({"ok": success}, status=200 if success else 503)

    async def cancel_navigation(request):
        session_id = protected_session(request)
        success = await controller.cancel_navigation(session_id)
        return web.json_response({"ok": success}, status=200 if success else 503)

    async def stand_up(request):
        session_id = protected_session(request)
        success = await controller.stand_up(session_id)
        return web.json_response({"ok": success}, status=200 if success else 503)

    async def stand_down(request):
        session_id = protected_session(request)
        success = await controller.stand_down(session_id)
        return web.json_response({"ok": success}, status=200 if success else 503)

    async def recovery_stand(request):
        session_id = protected_session(request)
        success = await controller.recovery_stand(session_id)
        return web.json_response({"ok": success}, status=200 if success else 503)

    async def emergency_stop(request):
        session_id = protected_session(request)
        success = await controller.emergency_stop(session_id)
        return web.json_response({"ok": success}, status=200 if success else 503)

    async def navigate_to_pose(request):
        session_id = protected_session(request)
        await _invoke(navigation_manager.require_ready)
        x, y, yaw = parse_pose(await parse_json(request))
        success = await controller.navigate_to_pose(session_id, x, y, yaw)
        return web.json_response({"ok": success}, status=200 if success else 503)

    async def navigate_through_poses(request):
        session_id = protected_session(request)
        await _invoke(navigation_manager.require_ready)
        data = await parse_json(request)
        raw_poses = data.get("poses")
        if not isinstance(raw_poses, list) or not 1 <= len(raw_poses) <= 100:
            raise ValueError("poses must contain between 1 and 100 items")
        poses = []
        for raw_pose in raw_poses:
            if not isinstance(raw_pose, dict):
                raise ValueError("every pose must be an object")
            x, y, yaw = parse_pose(raw_pose)
            poses.append({"x": x, "y": y, "yaw": yaw})
        success = await controller.navigate_through_poses(session_id, poses)
        return web.json_response({"ok": success}, status=200 if success else 503)

    async def set_initial_pose(request):
        session_id = protected_session(request)
        await _invoke(navigation_manager.require_stack_ready)
        x, y, yaw = parse_pose(await parse_json(request))
        success = await controller.set_initial_pose(session_id, x, y, yaw)
        if success:
            # Give the localization node time to consume /initialpose and seed
            # map->odom before goals become available in the Web UI.
            await asyncio.sleep(0.5)
            await _invoke(navigation_manager.mark_localized)
        return web.json_response({"ok": success}, status=200 if success else 503)

    async def mapping_status(request):
        authenticated_session(request)
        return web.json_response(await _invoke(mapping_manager.status))

    async def mapping_start(request):
        protected_session(request)
        state_data = await controller.state()
        if bool(state_data.get("nav_active", False)):
            raise MappingError("Nav2 正在执行任务，请先取消导航")
        navigation_state = await _invoke(navigation_manager.status)
        if bool(navigation_state.get("running", False)):
            raise MappingError("定位与 Nav2 正在运行，请先停止导航系统")
        result = await mapping_manager.start(nav_active=False)
        return web.json_response({"ok": True, **result})

    async def mapping_stop(request):
        protected_session(request)
        result = await mapping_manager.stop_and_save()
        return web.json_response({"ok": True, **result})

    async def mapping_convert(request):
        protected_session(request)
        result = await mapping_manager.convert_latest()
        return web.json_response({"ok": True, **result})

    async def mapping_map_bundle(request):
        authenticated_session(request)
        map_name = str(request.match_info.get("map_name", ""))
        payload = await _invoke(mapping_manager.map_bundle, map_name)
        archive_name = map_name.rsplit(".", 1)[0] + ".zip"
        return web.Response(
            body=payload,
            content_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{archive_name}"'
            },
        )

    async def navigation_system_status(request):
        authenticated_session(request)
        return web.json_response(await _invoke(navigation_manager.status))

    async def navigation_system_speed(request):
        authenticated_session(request)
        return web.json_response(await _invoke(navigation_manager.speed))

    async def navigation_system_speed_update(request):
        protected_session(request)
        data = await parse_json(request)
        result = await navigation_manager.set_speed(
            data.get("linear"), data.get("angular")
        )
        return web.json_response({"ok": True, **result})

    async def navigation_system_start(request):
        protected_session(request)
        mapping_state = await _invoke(mapping_manager.status)
        if bool(mapping_state.get("mapping_running", False)):
            raise NavigationError("FAST-LIO 正在建图，请先停止并保存当前建图")
        data = await parse_json(request)
        map_name = str(data.get("map_name", ""))
        result = await navigation_manager.start(map_name)
        return web.json_response({"ok": True, **result})

    async def navigation_system_stop(request):
        protected_session(request)
        await controller.force_stop()
        try:
            await _invoke(controller.ros_adapter.cancel_navigation)
        except Exception:
            # Stopping the owned Nav2 process groups remains the fail-safe path.
            pass
        result = await navigation_manager.stop()
        return web.json_response({"ok": True, **result})

    async def websocket_state(request):
        session_id = authenticated_session(request)
        origin = request.headers.get("Origin")
        if origin and origin not in {
            f"http://{request.host}",
            f"https://{request.host}",
        }:
            raise CsrfError("cross-origin WebSocket denied")
        websocket = web.WebSocketResponse(heartbeat=10.0, max_msg_size=4096)
        await websocket.prepare(request)
        disconnected = False

        async def disconnect_once():
            nonlocal disconnected
            if not disconnected:
                disconnected = True
                await controller.disconnect(session_id)

        async def publish_state():
            try:
                while not websocket.closed:
                    await websocket.send_json(await controller.state())
                    await asyncio.sleep(config.websocket_state_interval_sec)
            except (ConnectionResetError, RuntimeError):
                pass
            finally:
                await disconnect_once()

        publisher = asyncio.create_task(publish_state())
        try:
            async for message in websocket:
                if message.type == WSMsgType.TEXT:
                    try:
                        payload = json.loads(message.data)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("type") == "heartbeat":
                        try:
                            policy.heartbeat(session_id)
                        except ControlLeaseError:
                            pass
                elif message.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            publisher.cancel()
            await asyncio.gather(publisher, return_exceptions=True)
            await disconnect_once()
        return websocket

    async def websocket_ros(request):
        authenticated_session(request)
        origin = request.headers.get("Origin")
        if origin and origin not in {
            f"http://{request.host}",
            f"https://{request.host}",
        }:
            raise CsrfError("cross-origin WebSocket denied")

        browser = web.WebSocketResponse(
            heartbeat=10.0,
            max_msg_size=config.rosbridge_max_message_bytes,
        )
        await browser.prepare(request)
        try:
            async with ClientSession() as session:
                async with session.ws_connect(
                    config.rosbridge_url,
                    heartbeat=10.0,
                    max_msg_size=config.rosbridge_max_message_bytes,
                ) as upstream:

                    async def browser_to_upstream():
                        async for message in browser:
                            if message.type == WSMsgType.TEXT:
                                try:
                                    filtered = filter_client_message(message.data)
                                except RosbridgePolicyError as exc:
                                    await browser.send_json(
                                        {
                                            "op": "status",
                                            "level": "error",
                                            "msg": str(exc),
                                        }
                                    )
                                    continue
                                await upstream.send_json(filtered)
                            elif message.type in (
                                WSMsgType.ERROR,
                                WSMsgType.CLOSE,
                            ):
                                break

                    async def upstream_to_browser():
                        async for message in upstream:
                            if message.type == WSMsgType.TEXT:
                                await browser.send_str(message.data)
                            elif message.type in (
                                WSMsgType.ERROR,
                                WSMsgType.CLOSE,
                            ):
                                break

                    tasks = {
                        asyncio.create_task(browser_to_upstream()),
                        asyncio.create_task(upstream_to_browser()),
                    }
                    done, pending = await asyncio.wait(
                        tasks, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*done, *pending, return_exceptions=True)
        except (OSError, RuntimeError):
            if not browser.closed:
                await browser.send_json(
                    {
                        "op": "status",
                        "level": "error",
                        "msg": "ROS visualization is unavailable",
                    }
                )
        finally:
            if not browser.closed:
                await browser.close()
        return browser

    async def index(_request):
        index_path = Path(web_dir) / "index.html" if web_dir else None
        if index_path and index_path.is_file():
            return web.FileResponse(index_path)
        return web.json_response({"service": "Go2 LAN console", "ready": True})

    async def static_asset(request):
        if web_dir is None:
            raise web.HTTPNotFound()
        root = Path(web_dir).resolve()
        asset_path = request.match_info["asset_path"]
        try:
            path = (root / asset_path).resolve()
            path.relative_to(root)
        except (ValueError, OSError):
            raise web.HTTPNotFound()
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    app.router.add_post("/api/login", login)
    app.router.add_post("/api/logout", logout)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/control/acquire", acquire_control)
    app.router.add_post("/api/control/release", release_control)
    app.router.add_post("/api/stand-up", stand_up)
    app.router.add_post("/api/stand-down", stand_down)
    app.router.add_post("/api/recovery-stand", recovery_stand)
    app.router.add_post("/api/emergency-stop", emergency_stop)
    app.router.add_post("/api/manual", manual)
    app.router.add_post("/api/navigation/cancel", cancel_navigation)
    app.router.add_post("/api/navigation/goal", navigate_to_pose)
    app.router.add_post("/api/navigation/waypoints", navigate_through_poses)
    app.router.add_get("/api/navigation/system/status", navigation_system_status)
    app.router.add_get("/api/navigation/system/speed", navigation_system_speed)
    app.router.add_post(
        "/api/navigation/system/speed", navigation_system_speed_update
    )
    app.router.add_post("/api/navigation/system/start", navigation_system_start)
    app.router.add_post("/api/navigation/system/stop", navigation_system_stop)
    app.router.add_post("/api/localization/initialpose", set_initial_pose)
    app.router.add_get("/api/mapping/status", mapping_status)
    app.router.add_post("/api/mapping/start", mapping_start)
    app.router.add_post("/api/mapping/stop", mapping_stop)
    app.router.add_post("/api/mapping/convert", mapping_convert)
    app.router.add_get(
        "/api/mapping/maps/{map_name}/bundle", mapping_map_bundle
    )
    app.router.add_get("/ws/state", websocket_state)
    app.router.add_get("/ws/ros", websocket_ros)
    app.router.add_get("/", index)
    app.router.add_get("/{asset_path:.*}", static_asset)

    async def watchdog_context(_app):
        async def run():
            while True:
                await controller.watchdog_once()
                await asyncio.sleep(config.watchdog_interval_sec)

        task = asyncio.create_task(run())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await controller.force_stop()

    app.cleanup_ctx.append(watchdog_context)

    async def navigation_context(_app):
        try:
            yield
        finally:
            await navigation_manager.stop()

    app.cleanup_ctx.append(navigation_context)
    return app


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Go2 authenticated LAN console")
    parser.add_argument("--bind")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="run with a motion-free simulated ROS adapter",
    )
    parser.add_argument(
        "--password-hash-file",
        default="/etc/go2-console/password.hash",
    )
    arguments = parser.parse_args(argv)

    if arguments.demo:
        demo_password = os.environ.get("GO2_CONSOLE_DEMO_PASSWORD")
        if not demo_password:
            raise SystemExit(
                "GO2_CONSOLE_DEMO_PASSWORD is required when --demo is used"
            )
        from .console_core import hash_password

        password_hash = hash_password(demo_password)
    else:
        password_hash = Path(arguments.password_hash_file).read_text(
            encoding="utf-8"
        ).strip()
    policy = ConsolePolicy(
        config=ConsolePolicyConfig(
            username="operator",
            password_hash=password_hash,
        )
    )
    if arguments.demo:
        from .ros_adapter import DemoRosAdapter

        ros_adapter = DemoRosAdapter(
            nav2_status=os.environ.get("GO2_CONSOLE_DEMO_NAV_STATUS", "IDLE")
        )
    else:
        from .ros_adapter import RclpyRosAdapter

        ros_adapter = RclpyRosAdapter()
    bind_ip = arguments.bind or ("127.0.0.1" if arguments.demo else "192.168.0.101")
    web_dir = Path(__file__).with_name("web")
    app = create_app(
        policy=policy,
        ros_adapter=ros_adapter,
        config=ConsoleServerConfig(bind_ip=bind_ip, port=arguments.port),
        web_dir=web_dir,
    )

    async def close_ros(_app):
        ros_adapter.close()

    app.on_cleanup.append(close_ros)
    web.run_app(app, host=bind_ip, port=arguments.port, access_log=None)


if __name__ == "__main__":
    main()
