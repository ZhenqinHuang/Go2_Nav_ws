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

from go2_web_console.console_core import (  # noqa: E402
    ConsolePolicy,
    ConsolePolicyConfig,
    hash_password,
)
from go2_web_console.navigation_service import NavigationError  # noqa: E402


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
            "control_ready": True,
            "gateway_link": "online",
            "motion_mode": "idle",
            "velocity": {"vx": 0.0, "vy": 0.0, "vyaw": 0.0},
            "odometry": {"x": 1.0, "y": 2.0, "yaw": 0.3},
            "nav2_status": "IDLE",
        }
        self.calls = []

    def get_state(self):
        return dict(self.state_data)

    async def stand_up(self):
        self.calls.append(("stand_up",))
        return True

    async def stand_down(self):
        self.calls.append(("stand_down",))
        return True

    async def recovery_stand(self):
        self.calls.append(("recovery_stand",))
        return True

    async def emergency_stop(self):
        self.calls.append(("emergency_stop",))
        return True

    async def manual_command(self, vx, vy, vyaw):
        self.calls.append(("manual", vx, vy, vyaw))
        self.state_data["velocity"] = {"vx": vx, "vy": vy, "vyaw": vyaw}
        return True

    async def cancel_navigation(self):
        self.calls.append(("cancel_navigation",))
        self.state_data["nav2_status"] = "IDLE"
        return True

    async def navigate_to_pose(self, x, y, yaw):
        self.calls.append(("navigate_to_pose", x, y, yaw))
        self.state_data["nav2_status"] = "ACCEPTED"
        return True

    async def navigate_through_poses(self, poses):
        self.calls.append(("navigate_through_poses", poses))
        self.state_data["nav2_status"] = "ACCEPTED"
        return True

    async def set_initial_pose(self, x, y, yaw):
        self.calls.append(("set_initial_pose", x, y, yaw))
        return True


class FakeMappingManager:
    def __init__(self):
        self.calls = []
        self.state = {
            "mapping_running": False,
            "mapping_owned": False,
            "lidar_running": True,
            "session_pcd": None,
            "last_pcd": None,
            "message": "ready",
            "pointclouds": [],
            "maps": [],
        }

    def status(self):
        self.calls.append(("status",))
        return dict(self.state)

    async def start(self, *, nav_active=False):
        self.calls.append(("start", nav_active))
        self.state["mapping_running"] = True
        self.state["mapping_owned"] = True
        self.state["session_pcd"] = "map.pcd"
        return dict(self.state)

    async def stop_and_save(self):
        self.calls.append(("stop_and_save",))
        self.state["mapping_running"] = False
        self.state["mapping_owned"] = False
        self.state["last_pcd"] = {"name": "map.pcd", "bytes": 2048}
        return dict(self.state)

    async def convert_latest(self):
        self.calls.append(("convert_latest",))
        self.state["maps"] = [{"name": "map.yaml", "bytes": 200}]
        return dict(self.state)

    def map_bundle(self, map_name):
        self.calls.append(("map_bundle", map_name))
        return b"PK-map-bundle"


class FakeNavigationManager:
    def __init__(self):
        self.calls = []
        self.state = {
            "phase": "ready",
            "running": False,
            "ready": True,
            "stack_ready": True,
            "localized": True,
            "selected_map": "MID360_web_20260803_142003_map.yaml",
            "selected_pcd": "MID360_web_20260803_142003.pcd",
            "checks": {"navigate_to_pose": True, "initial_pose": True},
            "processes": {"nav2": True},
            "speed": {
                "linear": 0.25,
                "angular": 0.60,
                "limits": {
                    "linear_min": 0.05,
                    "linear_max": 0.60,
                    "angular_min": 0.10,
                    "angular_max": 1.40,
                },
            },
            "available_maps": [
                {
                    "map_name": "MID360_web_20260803_142003_map.yaml",
                    "pcd_name": "MID360_web_20260803_142003.pcd",
                }
            ],
            "message": "ready",
            "last_error": None,
        }

    def status(self):
        return dict(self.state)

    def speed(self):
        return dict(self.state["speed"])

    async def set_speed(self, linear, angular):
        self.calls.append(("set_speed", linear, angular))
        self.state["speed"] = {
            **self.state["speed"],
            "linear": float(linear),
            "angular": float(angular),
        }
        return self.speed()

    def require_ready(self):
        if not self.state["ready"]:
            raise NavigationError("定位与导航系统未就绪：/navigate_to_pose action")

    def require_stack_ready(self):
        if not self.state["stack_ready"]:
            raise NavigationError("定位与 Nav2 尚未完成启动")

    def mark_localized(self):
        self.calls.append(("mark_localized",))
        self.state["localized"] = True
        self.state["ready"] = True
        self.state["checks"]["initial_pose"] = True
        return dict(self.state)

    async def start(self, map_name):
        self.calls.append(("start", map_name))
        self.state["phase"] = "ready"
        self.state["running"] = True
        self.state["ready"] = True
        self.state["selected_map"] = map_name
        return dict(self.state)

    async def stop(self):
        self.calls.append(("stop",))
        self.state["phase"] = "idle"
        self.state["running"] = False
        self.state["ready"] = False
        return dict(self.state)


def load_server():
    spec = importlib.util.find_spec("go2_web_console.console_server")
    if spec is None:
        pytest.fail("console_server module is missing")
    return importlib.import_module("go2_web_console.console_server")


def async_test(function):
    @wraps(function)
    def run():
        return asyncio.run(function())

    return run


def make_app(
    module,
    *,
    clock=None,
    ros=None,
    mapping=None,
    navigation=None,
    rate_limit=100,
    max_body=4096,
):
    clock = clock or FakeClock()
    ros = ros or FakeRosAdapter()
    navigation = navigation or FakeNavigationManager()
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
    app = module.create_app(
        policy=policy,
        ros_adapter=ros,
        config=config,
        mapping_manager=mapping,
        navigation_manager=navigation,
    )
    return app, ros, clock


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
        with pytest.raises(WSServerHandshakeError) as ros_error:
            await client.ws_connect("/ws/ros")
        assert ros_error.value.status == 401


@async_test
async def test_readonly_ros_websocket_rejects_cross_origin_before_upstream():
    module = load_server()
    app, _ros, _clock = make_app(module)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        await login(client)
        with pytest.raises(WSServerHandshakeError) as error:
            await client.ws_connect(
                "/ws/ros", headers={"Origin": "http://malicious.example"}
            )
        assert error.value.status == 403


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
async def test_arm_endpoints_are_removed_and_cancel_navigation_remains():
    module = load_server()
    app, ros, _clock = make_app(module)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        _, data = await login(client)
        headers = {"X-CSRF-Token": data["csrf_token"]}
        await client.post("/api/control/acquire", headers=headers)

        assert (await client.post("/api/arm", headers=headers)).status == 405
        assert (await client.post("/api/disarm", headers=headers)).status == 405
        assert (
            await client.post("/api/navigation/cancel", headers=headers)
        ).status == 200
        assert [call[0] for call in ros.calls if call[0] != "manual"] == [
            "cancel_navigation",
        ]


@async_test
async def test_posture_and_emergency_endpoints_are_fixed_ros_actions():
    module = load_server()
    app, ros, _clock = make_app(module)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        _, data = await login(client)
        headers = {"X-CSRF-Token": data["csrf_token"]}
        await client.post("/api/control/acquire", headers=headers)

        assert (await client.post("/api/stand-up", headers=headers)).status == 200
        assert (await client.post("/api/stand-down", headers=headers)).status == 200
        assert (
            await client.post("/api/recovery-stand", headers=headers)
        ).status == 200
        assert (
            await client.post("/api/emergency-stop", headers=headers)
        ).status == 200
        assert [call[0] for call in ros.calls if call[0] != "manual"] == [
            "stand_up",
            "stand_down",
            "recovery_stand",
            "emergency_stop",
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
async def test_navigation_and_localization_require_auth_csrf_and_control_lease():
    module = load_server()
    app, _ros, _clock = make_app(module)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        payload = {"x": 1.0, "y": 2.0, "yaw": 0.3}
        assert (await client.post("/api/navigation/goal", json=payload)).status == 401

        _, data = await login(client)
        assert (await client.post("/api/navigation/goal", json=payload)).status == 403
        headers = {"X-CSRF-Token": data["csrf_token"]}
        assert (
            await client.post(
                "/api/navigation/goal", headers=headers, json=payload
            )
        ).status == 409
        await client.post("/api/control/acquire", headers=headers)
        assert (
            await client.post(
                "/api/navigation/goal", headers=headers, json=payload
            )
        ).status == 200


@async_test
async def test_mapping_status_requires_login_and_actions_do_not_require_motion_lease():
    module = load_server()
    mapping = FakeMappingManager()
    app, _ros, _clock = make_app(module, mapping=mapping)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        assert (await client.get("/api/mapping/status")).status == 401

        _, data = await login(client)
        status = await client.get("/api/mapping/status")
        assert status.status == 200
        assert (await status.json())["lidar_running"] is True

        assert (await client.post("/api/mapping/start")).status == 403
        headers = {"X-CSRF-Token": data["csrf_token"]}
        assert (await client.post("/api/mapping/start", headers=headers)).status == 200
        assert (await client.post("/api/mapping/stop", headers=headers)).status == 200
        assert (await client.post("/api/mapping/convert", headers=headers)).status == 200
        assert mapping.calls == [
            ("status",),
            ("start", False),
            ("stop_and_save",),
            ("convert_latest",),
        ]


@async_test
async def test_mapping_start_refuses_active_navigation_before_manager_action():
    module = load_server()
    ros = FakeRosAdapter()
    ros.state_data["nav2_status"] = "EXECUTING"
    mapping = FakeMappingManager()
    app, _ros, _clock = make_app(module, ros=ros, mapping=mapping)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        _, data = await login(client)
        headers = {"X-CSRF-Token": data["csrf_token"]}
        response = await client.post("/api/mapping/start", headers=headers)
        assert response.status == 409
        assert mapping.calls == []


@async_test
async def test_navigation_system_status_start_and_stop_use_fixed_api():
    module = load_server()
    mapping = FakeMappingManager()
    navigation = FakeNavigationManager()
    app, _ros, _clock = make_app(
        module, mapping=mapping, navigation=navigation
    )
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        assert (await client.get("/api/navigation/system/status")).status == 401
        _, data = await login(client)
        status = await client.get("/api/navigation/system/status")
        assert status.status == 200
        assert (await status.json())["available_maps"][0]["pcd_name"].endswith(
            ".pcd"
        )

        map_name = "MID360_web_20260803_142003_map.yaml"
        assert (
            await client.post(
                "/api/navigation/system/start", json={"map_name": map_name}
            )
        ).status == 403
        headers = {"X-CSRF-Token": data["csrf_token"]}
        started = await client.post(
            "/api/navigation/system/start",
            headers=headers,
            json={"map_name": map_name},
        )
        assert started.status == 200
        stopped = await client.post(
            "/api/navigation/system/stop", headers=headers
        )
        assert stopped.status == 200
        assert navigation.calls == [("start", map_name), ("stop",)]


@async_test
async def test_navigation_speed_uses_authenticated_fixed_api_and_csrf():
    module = load_server()
    navigation = FakeNavigationManager()
    app, _ros, _clock = make_app(module, navigation=navigation)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        assert (await client.get("/api/navigation/system/speed")).status == 401
        _, data = await login(client)

        response = await client.get("/api/navigation/system/speed")
        assert response.status == 200
        assert (await response.json())["linear"] == 0.25

        payload = {"linear": 0.10, "angular": 0.25}
        assert (
            await client.post("/api/navigation/system/speed", json=payload)
        ).status == 403
        response = await client.post(
            "/api/navigation/system/speed",
            headers={"X-CSRF-Token": data["csrf_token"]},
            json=payload,
        )
        assert response.status == 200
        assert await response.json() == {
            "ok": True,
            "linear": 0.10,
            "angular": 0.25,
            "limits": navigation.state["speed"]["limits"],
        }
        assert navigation.calls == [("set_speed", 0.10, 0.25)]


@async_test
async def test_navigation_system_refuses_mapping_and_goal_reports_readiness():
    module = load_server()
    mapping = FakeMappingManager()
    mapping.state["mapping_running"] = True
    navigation = FakeNavigationManager()
    navigation.state["ready"] = False
    app, _ros, _clock = make_app(
        module, mapping=mapping, navigation=navigation
    )
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        _, data = await login(client)
        headers = {"X-CSRF-Token": data["csrf_token"]}
        map_name = "MID360_web_20260803_142003_map.yaml"
        response = await client.post(
            "/api/navigation/system/start",
            headers=headers,
            json={"map_name": map_name},
        )
        assert response.status == 409
        assert "正在建图" in (await response.json())["error"]
        assert navigation.calls == []

        await client.post("/api/control/acquire", headers=headers)
        goal = await client.post(
            "/api/navigation/goal",
            headers=headers,
            json={"x": 1.0, "y": 2.0, "yaw": 0.0},
        )
        assert goal.status == 409
        assert "/navigate_to_pose" in (await goal.json())["error"]


@async_test
async def test_mapping_start_refuses_running_navigation_system():
    module = load_server()
    mapping = FakeMappingManager()
    navigation = FakeNavigationManager()
    navigation.state["running"] = True
    app, _ros, _clock = make_app(
        module, mapping=mapping, navigation=navigation
    )
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        _, data = await login(client)
        headers = {"X-CSRF-Token": data["csrf_token"]}
        response = await client.post("/api/mapping/start", headers=headers)
        assert response.status == 409
        assert "Nav2 正在运行" in (await response.json())["error"]
        assert mapping.calls == []


@async_test
async def test_web_generated_map_bundle_requires_login_and_uses_fixed_map_name():
    module = load_server()
    mapping = FakeMappingManager()
    app, _ros, _clock = make_app(module, mapping=mapping)
    path = "/api/mapping/maps/MID360_web_20260803_103915_map.yaml/bundle"
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        assert (await client.get(path)).status == 401
        await login(client)

        response = await client.get(path)

        assert response.status == 200
        assert response.content_type == "application/zip"
        assert await response.read() == b"PK-map-bundle"
        assert "MID360_web_20260803_103915_map.zip" in response.headers[
            "Content-Disposition"
        ]
        assert mapping.calls == [
            ("map_bundle", "MID360_web_20260803_103915_map.yaml")
        ]


@async_test
async def test_fixed_goal_waypoints_and_initialpose_operations():
    module = load_server()
    app, ros, _clock = make_app(module)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        _, data = await login(client)
        headers = {"X-CSRF-Token": data["csrf_token"]}
        await client.post("/api/control/acquire", headers=headers)

        goal = {"x": 1.25, "y": -0.5, "yaw": 1.2}
        waypoints = [
            {"x": 1.0, "y": 2.0, "yaw": 0.0},
            {"x": 3.0, "y": 4.0, "yaw": -1.0},
        ]
        assert (
            await client.post("/api/navigation/goal", headers=headers, json=goal)
        ).status == 200
        ros.state_data["nav2_status"] = "IDLE"
        assert (
            await client.post(
                "/api/navigation/waypoints",
                headers=headers,
                json={"poses": waypoints},
            )
        ).status == 200
        assert (
            await client.post(
                "/api/localization/initialpose", headers=headers, json=goal
            )
        ).status == 200
        assert [call[0] for call in ros.calls if call[0] != "manual"][-3:] == [
            "navigate_to_pose",
            "navigate_through_poses",
            "set_initial_pose",
        ]


@async_test
async def test_pose_validation_rejects_nonfinite_out_of_range_and_bad_lists():
    module = load_server()
    app, _ros, _clock = make_app(module)
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        _, data = await login(client)
        headers = {"X-CSRF-Token": data["csrf_token"]}
        await client.post("/api/control/acquire", headers=headers)

        invalid_goals = (
            {"x": "nan", "y": 0.0, "yaw": 0.0},
            {"x": 10001.0, "y": 0.0, "yaw": 0.0},
            {"x": 0.0, "y": 0.0, "yaw": 4.0},
        )
        for payload in invalid_goals:
            response = await client.post(
                "/api/navigation/goal", headers=headers, json=payload
            )
            assert response.status == 400

        empty = await client.post(
            "/api/navigation/waypoints",
            headers=headers,
            json={"poses": []},
        )
        oversized = await client.post(
            "/api/navigation/waypoints",
            headers=headers,
            json={
                "poses": [
                    {"x": float(index), "y": 0.0, "yaw": 0.0}
                    for index in range(101)
                ]
            },
        )
        assert empty.status == oversized.status == 400


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
