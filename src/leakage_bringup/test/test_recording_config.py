from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_record_topics_include_replayable_relay_outputs():
    topics = (ROOT / "config" / "record_topics.txt").read_text()
    assert "/record/odometry" in topics
    assert "/record/cloud_registered" in topics


def test_record_topics_skip_unavailable_realsense_metadata():
    topics = (ROOT / "config" / "record_topics.txt").read_text()
    assert "/camera/color/metadata" not in topics
    assert "/camera/depth/metadata" not in topics


def test_record_script_applies_qos_overrides():
    script = (ROOT / "scripts" / "record_leakage_session.sh").read_text()
    assert "--qos-profile-overrides-path" in script
    assert 'bash "$workspace/scripts/hardware_preflight.sh"' in script
    assert "tr -d '\\r'" in script
    assert "livox_ros_driver2/package.bash" in script


def test_preflight_waits_for_registered_cloud():
    source = (
        ROOT / "src" / "leakage_bringup" / "leakage_bringup" / "wait_for_topics.py"
    ).read_text()
    assert "PointCloud2" in source
    assert '"/record/cloud_registered"' in source
    assert '{"odom", "cloud", "rgb", "aligned_depth"}' in source


def test_realsense_starts_aligned_depth():
    script = (ROOT / "scripts" / "start_realsense_d435i.sh").read_text()
    assert "-p align.enable:=true" in script


def test_recording_includes_aligned_depth():
    topics = (ROOT / "config" / "record_topics.txt").read_text()
    assert "/camera/aligned_depth_to_color/image_raw" in topics
    assert "/camera/depth/image_rect_raw" not in topics
    assert "/camera/depth/camera_info" not in topics


def test_recording_includes_detection_outputs():
    topics = (ROOT / "config" / "record_topics.txt").read_text()
    assert "/leakage/mask" in topics
    assert "/leakage/points" in topics


def test_time_sync_check_uses_lidar_route_interface():
    script = (ROOT / "scripts" / "verify_time_sync.sh").read_text()
    assert "ip route get" in script
    assert "eth0" not in script
