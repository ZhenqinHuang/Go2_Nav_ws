from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "leakage_bringup"
    / "leakage_detector.py"
).read_text()


def test_detector_throttles_latest_frame_instead_of_inferring_in_rgb_callback():
    assert "create_timer" in SOURCE
    assert "self.rgb = message" in SOURCE


def test_detector_uses_jetson_cuda_fp16():
    assert "device=0" in SOURCE
    assert "half=True" in SOURCE
