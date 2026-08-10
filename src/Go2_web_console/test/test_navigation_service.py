import asyncio
from pathlib import Path
import sys
import time

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from go2_web_console.navigation_service import (  # noqa: E402
    NavigationError,
    NavigationManager,
)


class FakeProcess:
    next_pid = 5000

    def __init__(self, returncode=None):
        self.returncode = returncode
        self.pid = FakeProcess.next_pid
        FakeProcess.next_pid += 1

    def poll(self):
        return self.returncode


def manager_for(tmp_path):
    config = tmp_path / "mid360.yaml"
    config.write_text("/**:\n  ros__parameters: {}\n", encoding="utf-8")
    controller = tmp_path / "controller_server.yaml"
    controller.write_text(
        "controller_server:\n"
        "  ros__parameters:\n"
        "    FollowPath:\n"
        "      max_vel_x: 0.60\n"
        "      max_speed_xy: 0.60\n"
        "      max_vel_theta: 1.40\n"
        "      acc_lim_x: 1.20\n"
        "      decel_lim_x: -1.50\n"
        "      acc_lim_theta: 2.50\n"
        "      decel_lim_theta: -2.50\n",
        encoding="utf-8",
    )
    return NavigationManager(
        maps_dir=tmp_path / "maps",
        fastlio_config=config,
        controller_config=controller,
        runtime_dir=tmp_path / "runtime",
    )


def add_map_pair(manager, stamp="20260803_142003"):
    manager.maps_dir.mkdir(parents=True, exist_ok=True)
    base = f"MID360_web_{stamp}"
    pcd = manager.maps_dir / f"{base}.pcd"
    pgm = manager.maps_dir / f"{base}_map.pgm"
    yaml = manager.maps_dir / f"{base}_map.yaml"
    pcd.write_bytes(b"pcd")
    pgm.write_bytes(b"P5\n1 1\n255\n\xfe")
    yaml.write_text(f"image: {pgm.name}\nresolution: 0.05\n", encoding="utf-8")
    return yaml, pcd


def test_available_maps_only_returns_complete_safe_pairs(tmp_path):
    manager = manager_for(tmp_path)
    yaml, pcd = add_map_pair(manager)
    (manager.maps_dir / "MID360_web_20260803_150000_map.yaml").write_text(
        "image: missing.pgm\n", encoding="utf-8"
    )

    assert manager.available_maps() == [
        {
            "map_name": yaml.name,
            "pcd_name": pcd.name,
            "modified": manager.available_maps()[0]["modified"],
        }
    ]


def test_map_pair_rejects_missing_pcd_and_unsafe_name(tmp_path):
    manager = manager_for(tmp_path)
    manager.maps_dir.mkdir()
    name = "MID360_web_20260803_142003_map.yaml"
    (manager.maps_dir / name).write_text("image: map.pgm\n", encoding="utf-8")
    (manager.maps_dir / "map.pgm").write_bytes(b"pgm")

    with pytest.raises(NavigationError, match="配对文件"):
        manager._resolve_map_pair(name)
    with pytest.raises(NavigationError, match="Web 生成"):
        manager._resolve_map_pair("../map.yaml")


def test_wait_for_does_not_block_event_loop(tmp_path):
    manager = manager_for(tmp_path)

    def slow_ready_check():
        time.sleep(0.2)
        return True

    async def scenario():
        waiter = asyncio.create_task(
            manager._wait_for(slow_ready_check, timeout=1.0, error="not ready")
        )
        await asyncio.sleep(0.05)
        assert not waiter.done()
        await asyncio.wait_for(waiter, timeout=1.0)

    asyncio.run(scenario())


def test_start_owns_only_localization_and_nav2_processes(tmp_path, monkeypatch):
    manager = manager_for(tmp_path)
    yaml, _pcd = add_map_pair(manager)
    commands = {}

    monkeypatch.setattr(manager, "_livox_running", lambda: True)
    monkeypatch.setattr(manager, "_motion_gateway_active", lambda: True)
    monkeypatch.setattr(manager, "_external_processes", lambda: [])
    monkeypatch.setattr(manager, "_ros_graph_has", lambda _kind, _name: True)
    monkeypatch.setattr(manager, "_tf_available", lambda: True)
    monkeypatch.setattr(manager, "_nav2_lifecycle_active", lambda: True)
    monkeypatch.setattr(manager, "_navigate_action_available", lambda: True)

    def launch(name, command, _stamp):
        commands[name] = command
        process = FakeProcess()
        manager._processes[name] = process
        return process

    monkeypatch.setattr(manager, "_launch", launch)

    result = asyncio.run(manager.start(yaml.name))

    assert result["stack_ready"] is True
    assert result["ready"] is False
    assert result["phase"] == "awaiting_localization"
    assert set(commands) == set(manager.PROCESS_ORDER)
    combined = "\n".join(commands.values())
    assert "livox_ros_driver2" not in combined
    assert "udp_sender.launch.py" not in combined
    assert "go2-motion-sender" not in combined
    assert str(yaml) in commands["nav2"]
    assert str(_pcd) in commands["localization"]


def test_start_refuses_missing_long_running_prerequisite(tmp_path, monkeypatch):
    manager = manager_for(tmp_path)
    yaml, _pcd = add_map_pair(manager)
    monkeypatch.setattr(manager, "_livox_running", lambda: False)

    with pytest.raises(NavigationError, match="Livox"):
        asyncio.run(manager.start(yaml.name))

    assert manager._processes == {}


def test_speed_defaults_are_safe_and_persist_between_managers(tmp_path):
    manager = manager_for(tmp_path)

    assert manager.speed()["linear"] == 0.25
    assert manager.speed()["angular"] == 0.60
    asyncio.run(manager.set_speed(0.18, 0.40))

    restored = manager_for(tmp_path)
    assert restored.speed()["linear"] == 0.18
    assert restored.speed()["angular"] == 0.40


@pytest.mark.parametrize(
    "linear,angular",
    [(0.0, 0.3), (0.61, 0.3), (0.1, 0.09), (0.1, 1.41), (float("nan"), 0.3)],
)
def test_speed_rejects_values_outside_safe_bounds(tmp_path, linear, angular):
    manager = manager_for(tmp_path)

    with pytest.raises(NavigationError, match="速度"):
        asyncio.run(manager.set_speed(linear, angular))


def test_speed_cannot_change_while_navigation_system_is_running(tmp_path):
    manager = manager_for(tmp_path)
    manager._processes["nav2"] = FakeProcess()

    with pytest.raises(NavigationError, match="先停止"):
        asyncio.run(manager.set_speed(0.10, 0.20))


def test_speed_limits_are_rendered_into_complete_controller_config(tmp_path):
    manager = manager_for(tmp_path)
    asyncio.run(manager.set_speed(0.11, 0.25))
    rendered = manager._write_controller_config().read_text(encoding="utf-8")

    assert "max_vel_x: 0.11" in rendered
    assert "max_speed_xy: 0.11" in rendered
    assert "max_vel_theta: 0.25" in rendered
    assert "acc_lim_x: 1.2" in rendered
    assert "acc_lim_theta: 2.5" in rendered


def test_goals_remain_locked_until_operator_confirms_initial_pose(tmp_path, monkeypatch):
    manager = manager_for(tmp_path)
    monkeypatch.setattr(manager, "_livox_running", lambda: True)
    monkeypatch.setattr(manager, "_motion_gateway_active", lambda: True)
    manager._phase = "awaiting_localization"
    manager._checks = {name: name != "initial_pose" for name in manager.CHECK_ORDER}
    manager._processes = {name: FakeProcess() for name in manager.PROCESS_ORDER}

    with pytest.raises(NavigationError, match="人工重定位"):
        manager.require_ready()

    status = manager.mark_localized()
    assert status["localized"] is True
    assert status["ready"] is True


def test_start_refuses_non_web_owned_navigation_processes(tmp_path, monkeypatch):
    manager = manager_for(tmp_path)
    yaml, _pcd = add_map_pair(manager)
    monkeypatch.setattr(manager, "_livox_running", lambda: True)
    monkeypatch.setattr(manager, "_motion_gateway_active", lambda: True)
    monkeypatch.setattr(manager, "_external_processes", lambda: ["FAST-LIO"])

    with pytest.raises(NavigationError, match="非 Web 管理.*FAST-LIO"):
        asyncio.run(manager.start(yaml.name))


def test_require_ready_reports_specific_missing_checks(tmp_path, monkeypatch):
    manager = manager_for(tmp_path)
    add_map_pair(manager)
    monkeypatch.setattr(manager, "_livox_running", lambda: True)
    monkeypatch.setattr(manager, "_motion_gateway_active", lambda: True)

    with pytest.raises(NavigationError, match="/cloud_registered.*Nav2 lifecycle"):
        manager.require_ready()


def test_status_fails_closed_when_owned_process_exits(tmp_path, monkeypatch):
    manager = manager_for(tmp_path)
    add_map_pair(manager)
    monkeypatch.setattr(manager, "_livox_running", lambda: True)
    monkeypatch.setattr(manager, "_motion_gateway_active", lambda: True)
    manager._phase = "ready"
    manager._checks = {name: True for name in manager.CHECK_ORDER}
    manager._processes = {
        name: FakeProcess(returncode=1 if name == "nav2" else None)
        for name in manager.PROCESS_ORDER
    }

    status = manager.status()

    assert status["ready"] is False
    assert status["phase"] == "error"
    assert "nav2" in status["last_error"]
