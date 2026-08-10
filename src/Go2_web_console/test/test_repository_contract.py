from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_web_repository_has_only_web_runtime_boundaries():
    assert (ROOT / "go2_web_console").is_dir()
    assert (ROOT / "frontend").is_dir()
    assert (ROOT / "systemd" / "go2-console.service").is_file()
    assert (ROOT / "systemd" / "go2-console-rosbridge.service").is_file()
    assert not (ROOT / "internal_gateway").exists()

    forbidden = {
        "protocol.py",
        "sender_core.py",
        "udp_sender_node.py",
        "direct_sport_node.py",
    }
    present = {
        path.name
        for path in ROOT.rglob("*.py")
        if ".git" not in path.parts and "__pycache__" not in path.parts
    }
    assert forbidden.isdisjoint(present)


def test_web_repository_depends_on_public_ros_contract_only():
    adapter = read("go2_web_console/ros_adapter.py")

    assert "/go2/manual_cmd_vel" in adapter
    assert "/go2_cmd_vel_gateway/status" in adapter
    assert "/go2_cmd_vel_gateway/emergency_stop" in adapter
    assert "15000" not in adapter
    assert "15001" not in adapter
    assert "SportClient" not in adapter


def test_web_deployment_does_not_manage_motion_service():
    install_script = read("scripts/install_web_console.sh")

    assert "go2_web_console" in install_script
    assert "go2-console.service" in install_script
    assert "go2-motion-sender.service" not in install_script
    assert "internal_gateway" not in install_script
