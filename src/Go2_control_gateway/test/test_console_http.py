import asyncio
from functools import wraps
import importlib
import importlib.util
from pathlib import Path
import sys

from aiohttp import CookieJar, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer
import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from go2_control_gateway.console_core import (  # noqa: E402
    ConsolePolicy,
    ConsolePolicyConfig,
    hash_password,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeRosAdapter:
    def __init__(self):
        self.state_data = {
            "battery_percent": 76,
            "armed": False,
            "gateway_link": "online",
            "motion_mode": "idle",
            "velocity": {"vx": 0.0, "vy": 0.0, "vyaw": 0.0},
            "odometry": {"x": 1.0, "y": 2.0, "yaw": 0.3},
            "nav2_status": "IDLE",
        }
        self.calls = []

    def get_state(self):
        return dict(self.state_data)

    async def arm(self):
        self.calls.append(("arm",))
        self.state_data["armed"] = True
        return True

    async def disarm(self):
        self.calls.append(("disarm",))
        self.state_data["armed"] = False
        return True

    async def manual_command(self, vx, vy, vyaw):
        self.calls.append(("manual", vx, vy, vyaw))
        self.state_data["velocity"] = {"vx": vx, "vy": vy, "vyaw": vyaw}
        return True

    async def cancel_navigation(self):
        self.calls.append(("cancel_navigation",))
        self.state_data["nav2_status"] = "IDLE"
        return True


def load_server():
    spec = importlib.util.find_spec("go2_control_gateway.console_server")
    if spec is None:
        pytest.fail("console_server module is missing")
    return importlib.import_module("go2_control_gateway.console_server")


def async_test(function):
    @wraps(function)
    def run():
        return asyncio.run(function())

    return run


def make_app(module, *, clock=None, ros=None, rate_limit=100, max_body=4096):
    clock = clock or FakeClock()
    ros = ros or FakeRosAdapter()
    policy = ConsolePolicy(
        config=ConsolePolicyConfig(
            username="operator",
            password_hash=hash_password(
                "test-password-123",
                salt=b"0123456789abcdef",
                n=1024,
            ),
            session_idle_timeout_sec=60.0,
            session_absolute_timeout_sec=120.0,
            lease_timeout_sec=2.0,
            manual_timeout_sec=0.2,
        ),
        clock=clock,
        token_source=iter(
            [
                "session-one-opaque-value",
                "csrf-one-opaque-value",
                "session-two-opaque-value",
                "csrf-two-opaque-value",
            ]
        ).__next__,
    )
    config = module.ConsoleServerConfig(
        api_rate_limit=rate_limit,
        api_rate_window_sec=1.0,
        max_request_body_bytes=max_body,
        watchdog_interval_sec=60.0,
        websocket_state_interval_sec=0.01,
    )
    return module.create_app(policy=policy, ros_adapter=ros, config=config), ros, clock


async def login(client, *, username="operator", password="test-password-123"):
    response = await client.post(
        "/api/login",
        json={"username": username, "password": password},
    )
    data = await response.json()
    return response, data


@async_test
async def test_unauthenticated_api_and_websocket_are_rejected():
    module = load_server()
    app, _ros, _clock = make_app(module)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        response = await client.get("/api/state")
        assert response.status == 401
        with pytest.raises(WSServerHandshakeError) as error:
            await client.ws_connect("/ws/state")
        assert error.value.status == 401


@async_test
async def test_login_is_generic_and_sets_http_only_strict_cookie():
    module = load_server()
    app, _ros, _clock = make_app(module)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        bad_user, bad_user_data = await login(client, username="wrong")
        bad_password, bad_password_data = await login(client, password="wrong")
        assert bad_user.status == bad_password.status == 401
        assert bad_user_data == bad_password_data == {"error": "invalid credentials"}

        response, data = await login(client)
        cookie = response.headers["Set-Cookie"]
        assert response.status == 200
        assert data["csrf_token"]
        assert "HttpOnly" in cookie
        assert "SameSite=Strict" in cookie
        assert "Secure" not in cookie


@async_test
async def test_state_changes_require_csrf_token():
    module = load_server()
    app, _ros, _clock = make_app(module)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        _response, data = await login(client)
        missing = await client.post("/api/control/acquire")
        wrong = await client.post(
            "/api/control/acquire", headers={"X-CSRF-Token": "wrong"}
        )
        correct = await client.post(
            "/api/control/acquire",
            headers={"X-CSRF-Token": data["csrf_token"]},
        )
        assert missing.status == wrong.status == 403
        assert correct.status == 200


@async_test
async def test_single_control_lease_conflicts_and_can_be_released():
    module = load_server()
    app, _ros, _clock = make_app(module)
    server = TestServer(app)
    first = TestClient(server, cookie_jar=CookieJar(unsafe=True))
    second = TestClient(server, cookie_jar=CookieJar(unsafe=True))
    await first.start_server()
    await second.start_server()
    try:
        _, first_login = await login(first)
        _, second_login = await login(second)
        first_headers = {"X-CSRF-Token": first_login["csrf_token"]}
        second_headers = {"X-CSRF-Token": second_login["csrf_token"]}

        assert (await first.post("/api/control/acquire", headers=first_headers)).status == 200
        assert (await second.post("/api/control/acquire", headers=second_headers)).status == 409
        assert (await first.post("/api/control/release", headers=first_headers)).status == 200
        assert (await second.post("/api/control/acquire", headers=second_headers)).status == 200
    finally:
        await first.close()
        await second.close()


@async_test
async def test_arm_disarm_and_cancel_navigation_are_fixed_ros_actions():
    module = load_server()
    app, ros, _clock = make_app(module)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        _, data = await login(client)
        headers = {"X-CSRF-Token": data["csrf_token"]}
        await client.post("/api/control/acquire", headers=headers)

        assert (await client.post("/api/arm", headers=headers)).status == 200
        assert (await client.post("/api/control/release", headers=headers)).status == 200
        assert (await client.post("/api/disarm", headers=headers)).status == 200
        await client.post("/api/control/acquire", headers=headers)
        assert (
            await client.post("/api/navigation/cancel", headers=headers)
        ).status == 200
        assert [call[0] for call in ros.calls if call[0] != "manual"] == [
            "arm",
            "disarm",
            "cancel_navigation",
        ]


@async_test
async def test_nav2_active_rejects_manual_and_browser_timeout_sends_zero():
    module = load_server()
    app, ros, clock = make_app(module)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        _, data = await login(client)
        headers = {"X-CSRF-Token": data["csrf_token"]}
        await client.post("/api/control/acquire", headers=headers)
        ros.state_data["nav2_status"] = "EXECUTING"

        blocked = await client.post(
            "/api/manual",
            headers=headers,
            json={"vx": 0.2, "vy": 0.0, "vyaw": 0.0},
        )
        assert blocked.status == 409

        ros.state_data["nav2_status"] = "IDLE"
        moving = await client.post(
            "/api/manual",
            headers=headers,
            json={"vx": 0.2, "vy": 0.0, "vyaw": 0.1},
        )
        assert moving.status == 200
        clock.advance(0.21)
        await app[module.CONSOLE_CONTROLLER_KEY].watchdog_once()
        assert ros.calls[-1] == ("manual", 0.0, 0.0, 0.0)


@async_test
async def test_logout_and_websocket_disconnect_release_and_stop():
    module = load_server()
    app, ros, _clock = make_app(module)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        _, data = await login(client)
        headers = {"X-CSRF-Token": data["csrf_token"]}
        await client.post("/api/control/acquire", headers=headers)
        websocket = await client.ws_connect("/ws/state")
        await websocket.receive_json()
        await websocket.close()
        await asyncio.sleep(0.02)
        await app[module.CONSOLE_CONTROLLER_KEY].watchdog_once()
        assert ros.calls[-1] == ("manual", 0.0, 0.0, 0.0)

        # Log in again because disconnect releases control, but not authentication.
        await client.post("/api/control/acquire", headers=headers)
        response = await client.post("/api/logout", headers=headers)
        assert response.status == 200
        await app[module.CONSOLE_CONTROLLER_KEY].watchdog_once()
        assert ros.calls[-1] == ("manual", 0.0, 0.0, 0.0)


@async_test
async def test_api_rate_and_request_body_limits():
    module = load_server()
    app, _ros, _clock = make_app(module, rate_limit=2, max_body=512)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        first = await client.get("/api/state")
        second = await client.get("/api/state")
        limited = await client.get("/api/state")
        assert first.status == second.status == 401
        assert limited.status == 429

    app2, _ros2, _clock2 = make_app(module, max_body=128)
    async with TestClient(TestServer(app2), cookie_jar=CookieJar(unsafe=True)) as client:
        oversized = await client.post(
            "/api/login",
            data="x" * 1024,
            headers={"Content-Type": "application/json"},
        )
        assert oversized.status == 413
