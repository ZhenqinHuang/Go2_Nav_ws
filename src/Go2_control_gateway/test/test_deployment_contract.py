from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "src" / "Go2_control_gateway"
BRINGUP = ROOT / "src" / "Go2_bringup"


def text(path):
    assert path.is_file(), f"missing deployment asset: {path}"
    return path.read_text(encoding="utf-8")


def test_internal_service_uses_eth0_control_network_and_restarts_locked():
    service = text(PACKAGE / "systemd" / "go2-cmd-gateway.service")
    environment = text(PACKAGE / "config" / "internal_gateway.env")

    assert "192.168.123.18" in environment
    assert "192.168.123.5" in environment
    assert "eth0" in environment
    assert "15000" in environment
    assert "Restart=on-failure" in service
    assert "--interface" in service
    assert "--bind" in service
    assert "ExecStop" in service


def test_console_service_runs_as_nvidia_on_management_lan_not_root():
    service = text(PACKAGE / "systemd" / "go2-console.service")

    assert "User=nvidia" in service
    assert "User=root" not in service
    assert "192.168.0.101" in service
    assert "8080" in service
    assert "Restart=on-failure" in service


def test_console_service_does_not_bind_ros_to_the_go2_only_interface():
    service = text(PACKAGE / "systemd" / "go2-console.service")

    assert "unitree_ros2/install/setup.bash" in service
    assert "unitree_ros2/setup.sh" not in service
    assert "RMW_IMPLEMENTATION=rmw_fastrtps_cpp" in service


def test_deployment_scripts_contain_no_plaintext_board_passwords():
    paths = [
        PACKAGE / "scripts" / "deploy_internal_gateway.sh",
        PACKAGE / "scripts" / "install_external_services.sh",
        BRINGUP / "go2_gateway_arm.sh",
        BRINGUP / "go2_gateway_disarm.sh",
        BRINGUP / "go2_gateway_status.sh",
    ]
    combined = "\n".join(text(path) for path in paths).lower()

    assert "unitree / 123" not in combined
    assert "password=123" not in combined
    assert "nvidia/nvidia" not in combined
    assert "sshpass" not in combined


def test_normal_nav2_uses_udp_sender_but_direct_dds_fallback_is_preserved():
    run_nav2 = text(BRINGUP / "run_nav2.sh")

    assert "GO2_CONTROL_BACKEND" in run_nav2
    assert 'GO2_CONTROL_BACKEND="${GO2_CONTROL_BACKEND:-udp}"' in run_nav2
    assert "go2_control_gateway udp_sender.launch.py" in run_nav2
    assert "go2_nav2 cmd_vel_bridge.launch.py" in run_nav2
    assert (ROOT / "src" / "Go2_nav2" / "launch" / "cmd_vel_bridge.launch.py").is_file()


def test_shutdown_and_operator_scripts_disarm_before_stopping_services():
    disarm = text(BRINGUP / "go2_gateway_disarm.sh")
    external_install = text(
        PACKAGE / "scripts" / "install_external_services.sh"
    )

    assert "/go2_cmd_vel_gateway/arm" in disarm
    assert "data: false" in disarm
    assert "go2_gateway_disarm.sh" in external_install
    assert external_install.index("go2_gateway_disarm.sh") < external_install.index(
        "systemctl stop"
    )


def test_web_startup_uses_authenticated_console_and_any_legacy_bridge_is_loopback():
    script = text(BRINGUP / "run_robot_web.sh")

    assert "go2_console" in script
    assert "192.168.0.101" in script
    if "rosbridge_websocket" in script:
        assert "127.0.0.1" in script
