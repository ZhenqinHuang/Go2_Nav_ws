import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "map_bundle", ROOT / "scripts" / "map_bundle.py"
)
map_bundle = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(map_bundle)


def write_bundle(root: Path, bundle_id: str = "test-map") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "MID360.pcd").write_bytes(b"pcd-data")
    (root / "MID360_map.pgm").write_bytes(b"P5\n1 1\n255\n\0")
    (root / "MID360_map.yaml").write_text(
        "image: MID360_map.pgm\nresolution: 0.05\n"
        "origin: [0.0, 0.0, 0.0]\nnegate: 0\n"
        "occupied_thresh: 0.65\nfree_thresh: 0.196\n",
        encoding="utf-8",
    )
    map_bundle.create_manifest(root, bundle_id=bundle_id)


def test_complete_bundle_validates_and_records_sha256(tmp_path):
    write_bundle(tmp_path)

    manifest = map_bundle.validate_bundle(tmp_path)

    assert manifest["schema_version"] == 1
    assert manifest["bundle_id"] == "test-map"
    expected = hashlib.sha256((tmp_path / "MID360.pcd").read_bytes()).hexdigest()
    assert manifest["files"]["MID360.pcd"]["sha256"] == expected


def test_sha256_mismatch_is_rejected(tmp_path):
    write_bundle(tmp_path)
    (tmp_path / "MID360.pcd").write_bytes(b"pcd-datx")

    with pytest.raises(map_bundle.BundleError, match="SHA-256"):
        map_bundle.validate_bundle(tmp_path)


def test_yaml_must_reference_the_canonical_pgm(tmp_path):
    write_bundle(tmp_path)
    (tmp_path / "MID360_map.yaml").write_text(
        "image: other.pgm\nresolution: 0.05\n", encoding="utf-8"
    )
    map_bundle.create_manifest(tmp_path, bundle_id="bad-image")

    with pytest.raises(map_bundle.BundleError, match="MID360_map.pgm"):
        map_bundle.validate_bundle(tmp_path)


def test_incomplete_staging_never_changes_active_bundle(tmp_path):
    active = tmp_path / "maps"
    staging = tmp_path / "staging"
    archive = tmp_path / "archive"
    write_bundle(active, "active-v1")
    before = (active / "MID360.pcd").read_bytes()
    staging.mkdir()
    (staging / "MID360.pcd").write_bytes(b"partial")

    with pytest.raises(map_bundle.BundleError):
        map_bundle.promote_bundle(staging, active, archive)

    assert (active / "MID360.pcd").read_bytes() == before
    assert map_bundle.validate_bundle(active)["bundle_id"] == "active-v1"


def test_promotion_archives_previous_complete_bundle(tmp_path):
    active = tmp_path / "maps"
    staging = tmp_path / "staging"
    archive = tmp_path / "archive"
    write_bundle(active, "active-v1")
    write_bundle(staging, "active-v2")

    promoted = map_bundle.promote_bundle(staging, active, archive)

    assert promoted["bundle_id"] == "active-v2"
    archived = archive / "active-v1"
    assert map_bundle.validate_bundle(archived)["bundle_id"] == "active-v1"
    assert map_bundle.validate_bundle(active)["bundle_id"] == "active-v2"
    assert json.loads((active / "map_manifest.yaml").read_text())["bundle_id"] == "active-v2"


def test_localization_and_nav2_defaults_use_only_the_canonical_active_pair():
    localization = (
        ROOT
        / "src/Go2_localization/fast_lio_localization_ros2/launch/localize_go2.launch.py"
    ).read_text(encoding="utf-8")
    nav2 = (ROOT / "src/Go2_nav2/launch/nav2_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert "/home/nvidia/Go2_Nav_ws/maps/MID360.pcd" in localization
    assert "/home/nvidia/Go2_Nav_ws/maps/MID360_map.yaml" in nav2
    assert "MID360_web_" not in localization + nav2
