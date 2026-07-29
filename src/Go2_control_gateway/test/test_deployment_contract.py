from pathlib import Path
import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
STANDALONE = not (
    PACKAGE_ROOT.parent.name == "src"
    and (PACKAGE_ROOT.parent / "Go2_bringup").is_dir()
)
if STANDALONE:
    ROOT = PACKAGE_ROOT
    PACKAGE = PACKAGE_ROOT
    BRINGUP = PACKAGE_ROOT.parent / "Go2_bringup"
else:
    ROOT = Path(__file__).resolve().parents[3]
    PACKAGE = ROOT / "src" / "Go2_control_gateway"
    BRINGUP = ROOT / "src" / "Go2_bringup"

requires_bringup = pytest.mark.skipif(
    not BRINGUP.is_dir(),
    reason="requires the companion Go2_bringup package from Go2_Nav_ws",
)


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


def test_internal_sdk_build_matches_the_installed_unitree_sdk_layout():
    cmake = text(PACKAGE / "internal_gateway" / "CMakeLists.txt")
    adapter = text(
        PACKAGE / "internal_gateway" / "src" / "unitree_sport_api.cpp"
    )

    assert "unitree::robot::SportClient" in adapter
    assert "unitree::robot::go2::SportClient" not in adapter
    assert "UNITREE_DDSCXX_INCLUDE_DIR" in cmake
    assert "UNITREE_ICEORYX_INCLUDE_DIR" in cmake
    assert "UNITREE_DDSCXX_LIBRARY" in cmake
    assert "UNITREE_DDSC_LIBRARY" in cmake


def test_unitree_client_is_constructed_after_channel_factory_initialization():
    adapter = text(
        PACKAGE / "internal_gateway" / "src" / "unitree_sport_api.cpp"
    )

    client_factory = "std::make_unique<unitree::robot::SportClient>"
    assert client_factory in adapter
    factory_init = adapter.index("ChannelFactory::Instance()->Init")
    client_construction = adapter.index(client_factory)

    assert factory_init < client_construction
    assert (
        "std::unique_ptr<unitree::robot::SportClient> client_;" in adapter
    )


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
    combined = "\n".join(text(path) for path in paths if path.is_file()).lower()

    assert "unitree / 123" not in combined
    assert "password=123" not in combined
    assert "nvidia/nvidia" not in combined
    assert "sshpass" not in combined


@requires_bringup
def test_normal_nav2_uses_udp_sender_but_direct_dds_fallback_is_preserved():
    run_nav2 = text(BRINGUP / "run_nav2.sh")

    assert "GO2_CONTROL_BACKEND" in run_nav2
    assert 'GO2_CONTROL_BACKEND="${GO2_CONTROL_BACKEND:-udp}"' in run_nav2
    assert "go2_control_gateway udp_sender.launch.py" in run_nav2
    assert "go2_nav2 cmd_vel_bridge.launch.py" in run_nav2
    assert (ROOT / "src" / "Go2_nav2" / "launch" / "cmd_vel_bridge.launch.py").is_file()


@requires_bringup
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


@requires_bringup
def test_web_startup_uses_authenticated_console_and_any_legacy_bridge_is_loopback():
    script = text(BRINGUP / "run_robot_web.sh")

    assert "go2_console" in script
    assert "192.168.0.101" in script
    if "rosbridge_websocket" in script:
        assert "127.0.0.1" in script


def test_visualization_rosbridge_is_loopback_only_and_console_depends_on_it():
    rosbridge = text(PACKAGE / "systemd" / "go2-console-rosbridge.service")
    console = text(PACKAGE / "systemd" / "go2-console.service")

    assert "rosbridge_websocket" in rosbridge
    assert "127.0.0.1" in rosbridge
    assert "9090" in rosbridge
    assert "0.0.0.0" not in rosbridge
    assert "go2-console-rosbridge.service" in console
    assert "After=" in console


def test_external_installer_builds_frontend_before_colcon_without_network_edits():
    installer = text(PACKAGE / "scripts" / "install_external_services.sh")
    frontend_build = text(PACKAGE / "scripts" / "build_frontend.sh")
    combined = f"{installer}\n{frontend_build}"

    assert "build_frontend.sh" in installer
    assert installer.index("build_frontend.sh") < installer.index("colcon build")
    assert "npm ci" in frontend_build
    assert "npm run build" in frontend_build
    assert "go2_control_gateway/web" in frontend_build
    assert "GO2_SKIP_FRONTEND_BUILD" in installer
    assert "production bundle is incomplete" in installer
    for forbidden in ("nmcli", "ip addr add", "ip route add", "netplan"):
        assert forbidden not in combined
