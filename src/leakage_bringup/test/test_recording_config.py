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


def test_preflight_waits_for_registered_cloud():
    source = (
        ROOT / "src" / "leakage_bringup" / "leakage_bringup" / "wait_for_topics.py"
    ).read_text()
    assert "PointCloud2" in source
    assert '"/record/cloud_registered"' in source
    assert '{"odom", "cloud", "rgb", "depth"}' in source
