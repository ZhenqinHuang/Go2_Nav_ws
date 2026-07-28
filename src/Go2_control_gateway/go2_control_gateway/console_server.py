"""Authenticated aiohttp backend for the trusted-LAN Go2 console."""

import argparse
import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
import inspect
import json
import os
from pathlib import Path
import time
from typing import Callable, Optional

from aiohttp import WSMsgType, web

from .console_core import (
    AuthenticationError,
    ConsolePolicy,
    ConsolePolicyConfig,
    ControlLeaseError,
    ManualControlError,
)


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
    result = await asyncio.to_thread(method, *args)
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

    async def arm(self, session_id: str) -> bool:
        self.policy.authorize_arm(session_id)
        return bool(await _invoke(self.ros_adapter.arm))

    async def disarm(self, session_id: str) -> bool:
        self.policy.authorize_disarm(session_id)
        await self.force_stop()
        return bool(await _invoke(self.ros_adapter.disarm))

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


def create_app(
    *,
    policy: ConsolePolicy,
    ros_adapter,
    config: Optional[ConsoleServerConfig] = None,
    web_dir: Optional[Path] = None,
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
        except (ControlLeaseError, ManualControlError) as exc:
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

    async def arm(request):
        session_id = protected_session(request)
        success = await controller.arm(session_id)
        return web.json_response({"ok": success}, status=200 if success else 503)

    async def disarm(request):
        session_id = protected_session(request)
        success = await controller.disarm(session_id)
        return web.json_response({"ok": success}, status=200 if success else 503)

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

    async def index(_request):
        index_path = Path(web_dir) / "index.html" if web_dir else None
        if index_path and index_path.is_file():
            return web.FileResponse(index_path)
        return web.json_response({"service": "Go2 LAN console", "ready": True})

    async def static_asset(request):
        if web_dir is None:
            raise web.HTTPNotFound()
        filename = request.match_info["filename"]
        if filename not in {"app.css", "app.js", "favicon.svg"}:
            raise web.HTTPNotFound()
        path = Path(web_dir) / filename
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    app.router.add_post("/api/login", login)
    app.router.add_post("/api/logout", logout)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/control/acquire", acquire_control)
    app.router.add_post("/api/control/release", release_control)
    app.router.add_post("/api/arm", arm)
    app.router.add_post("/api/disarm", disarm)
    app.router.add_post("/api/manual", manual)
    app.router.add_post("/api/navigation/cancel", cancel_navigation)
    app.router.add_get("/ws/state", websocket_state)
    app.router.add_get("/", index)
    app.router.add_get(
        "/{filename:(?:app\\.(?:css|js)|favicon\\.svg)}", static_asset
    )

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
