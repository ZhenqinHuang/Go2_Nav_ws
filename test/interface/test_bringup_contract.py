from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_root_entry_scripts_are_thin_stable_wrappers():
    for name in (
        "start_mapping.sh",
        "start_navigation.sh",
        "check_system.sh",
        "stop_all.sh",
    ):
        text = read(f"scripts/{name}")
        assert text.startswith("#!/usr/bin/env bash")
        assert "Go2_bringup" in text or name == "check_system.sh"
        assert "unitree" not in text
        assert "192.168.123.99" not in text


def test_navigation_bringup_uses_canonical_order_and_udp_only():
    script = read("src/Go2_bringup/start_navigation.sh")
    expected = (
        "livox_ros_driver2",
        "fast_lio",
        "odom_tf_bridge",
        "fast_lio_localization_ros2",
        "go2_pc2scan",
        "go2_nav2",
    )
    positions = [script.index(value) for value in expected]
    assert positions == sorted(positions)
    assert "go2-motion-sender.service" in script
    assert "MID360.pcd" in script
    assert "MID360_map.yaml" in script
    assert "go2_cmd_vel_bridge" not in script
    assert "direct_sport" not in script
    assert not re.search(r"\bsleep\s+(8|10|30|60)(?:\.0)?\b", script)
    assert "wait_tf map base_link" in script
    assert "timeout 20 ros2 run tf2_ros tf2_echo" not in script


def test_system_check_has_actionable_readiness_stages():
    script = read("src/Go2_bringup/check_system.sh")
    for evidence in (
        "NTPSynchronized",
        "192.168.0.101",
        "192.168.123.5",
        "192.168.1.5",
        "192.168.123.18",
        "192.168.123.161",
        "192.168.1.158",
        "map_bundle.py",
        "/Odometry",
        "/cloud_registered",
        "/odom",
        "/scan",
        "/map_to_odom",
        "tf2_echo map base_link",
        "go2-motion-sender.service",
        "/go2_cmd_vel_gateway/status",
        "estop_latched",
        "ros2 lifecycle get",
        "/navigate_to_pose",
    ):
        assert evidence in script
    for code in ("EXIT_BASE=10", "EXIT_CONTROL=20", "EXIT_PERCEPTION=30", "EXIT_LOCALIZATION=40", "EXIT_NAV2=50"):
        assert code in script


def test_formal_services_replace_vite_and_wait_for_time_validity():
    bringup = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/Go2_bringup").glob("*.sh")
    )
    assert "vite" not in bringup.lower()
    assert "5173" not in bringup

    web = read("src/Go2_web_console/systemd/go2-console.service")
    sender = read("src/Go2_control_gateway/systemd/go2-motion-sender.service")
    ptp = read("src/Go2_time_sync/config/ptp_sync.service")
    for service in (web, sender, ptp):
        assert "time-sync.target" in service
        assert "/home/unitree" not in service
    assert "ExecStartPre=/bin/sleep" not in ptp


def test_direct_dds_bridge_is_compile_time_disabled_by_default():
    cmake = read("src/Go2_nav2/CMakeLists.txt")
    package = read("src/Go2_nav2/package.xml")
    launch = read("src/Go2_nav2/launch/nav2_bringup.launch.py")

    assert "GO2_BUILD_DIRECT_DDS_BRIDGE OFF" in cmake
    assert "if(GO2_BUILD_DIRECT_DDS_BRIDGE)" in cmake
    assert "go2_cmd_vel_bridge_node" not in launch
    assert "unitree_api" not in package


def test_keyboard_direct_dds_maintenance_is_explicit_and_mutually_exclusive():
    script = read("src/Go2_bringup/run_keyboard_teleop.sh")
    assert "GO2_ALLOW_DIRECT_DDS" in script
    assert "systemctl is-active --quiet go2-motion-sender.service" in script
    assert "sleep 1" not in script
