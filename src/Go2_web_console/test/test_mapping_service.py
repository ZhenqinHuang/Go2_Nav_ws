import asyncio
import io
from pathlib import Path
import sys
import time
import zipfile

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from go2_web_console.mapping_service import MappingError, MappingManager  # noqa: E402


def manager_for(tmp_path):
    config = tmp_path / "mid360.yaml"
    config.write_text(
        '/**:\n  ros__parameters:\n    map_file_path: "/old/map.pcd"\n',
        encoding="utf-8",
    )
    return MappingManager(
        maps_dir=tmp_path / "maps",
        fastlio_config=config,
        runtime_dir=tmp_path / "runtime",
        map_bundle_tool=PACKAGE_ROOT.parents[1] / "scripts" / "map_bundle.py",
    )


def test_session_config_uses_unique_output_without_changing_source(tmp_path):
    manager = manager_for(tmp_path)
    output = manager.runtime_dir / "session.yaml"
    output.parent.mkdir(parents=True)
    pcd = manager.maps_dir / "MID360_web_20260803_120000.pcd"

    manager._write_session_config(output, pcd)

    assert str(pcd) in output.read_text(encoding="utf-8")
    assert "/old/map.pcd" in manager.fastlio_config.read_text(encoding="utf-8")


def test_status_lists_only_web_generated_maps(tmp_path, monkeypatch):
    manager = manager_for(tmp_path)
    manager.maps_dir.mkdir()
    (manager.maps_dir / "MID360_web_20260803_120000.pcd").write_bytes(b"p" * 2048)
    (manager.maps_dir / "MID360_web_20260803_120000_map.yaml").write_text("map")
    (manager.maps_dir / "MID360.pcd").write_bytes(b"legacy")
    monkeypatch.setattr(manager, "_fastlio_running", lambda: False)
    monkeypatch.setattr(manager, "_livox_running", lambda: True)

    status = manager.status()

    assert [item["name"] for item in status["pointclouds"]] == [
        "MID360_web_20260803_120000.pcd"
    ]
    assert [item["name"] for item in status["maps"]] == [
        "MID360_web_20260803_120000_map.yaml"
    ]


def test_start_rejects_existing_fastlio_before_writing_files(tmp_path, monkeypatch):
    manager = manager_for(tmp_path)
    monkeypatch.setattr(manager, "_fastlio_running", lambda: True)

    with pytest.raises(MappingError, match="FAST-LIO"):
        asyncio.run(manager.start())

    assert not manager.maps_dir.exists()


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


def test_map_bundle_contains_matching_yaml_and_pgm(tmp_path):
    manager = manager_for(tmp_path)
    manager.maps_dir.mkdir()
    name = "MID360_map.yaml"
    pgm_name = "MID360_map.pgm"
    (manager.maps_dir / name).write_text(
        f"image: {manager.maps_dir / pgm_name}\nresolution: 0.05\n",
        encoding="utf-8",
    )
    (manager.maps_dir / pgm_name).write_bytes(b"P5\n1 1\n255\n\xfe")

    payload = manager.map_bundle(name)

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert sorted(archive.namelist()) == sorted([name, pgm_name])
        assert archive.read(pgm_name).endswith(b"\xfe")


@pytest.mark.parametrize(
    "name",
    ["../MID360_web_20260803_120000_map.yaml", "map.yaml", "bad.zip"],
)
def test_map_bundle_rejects_non_web_or_unsafe_names(tmp_path, name):
    manager = manager_for(tmp_path)
    with pytest.raises(MappingError, match="地图名称"):
        manager.map_bundle(name)


def test_conversion_stages_and_promotes_a_complete_canonical_bundle(
    tmp_path, monkeypatch
):
    manager = manager_for(tmp_path)
    manager.maps_dir.mkdir()
    source = manager.maps_dir / "MID360_web_20260803_120000.pcd"
    source.write_bytes(b"pcd" * 1024)
    manager._current_pcd = source
    monkeypatch.setattr(manager, "_fastlio_running", lambda: False)
    monkeypatch.setattr(manager, "_livox_running", lambda: True)

    async def fake_convert(command, *, timeout):
        output = command.split("output_path:=", 1)[1]
        prefix = Path(output)
        prefix.with_suffix(".pgm").write_bytes(b"P5\n1 1\n255\n\0")
        prefix.with_suffix(".yaml").write_text(
            f"image: {prefix}.pgm\nresolution: 0.05\n",
            encoding="utf-8",
        )
        return "ok"

    monkeypatch.setattr(manager, "_run_ros", fake_convert)

    asyncio.run(manager.convert_latest())

    assert (manager.maps_dir / "MID360.pcd").read_bytes() == source.read_bytes()
    assert (manager.maps_dir / "MID360_map.pgm").is_file()
    assert "image: MID360_map.pgm" in (
        manager.maps_dir / "MID360_map.yaml"
    ).read_text(encoding="utf-8")
    assert (manager.maps_dir / "map_manifest.yaml").is_file()
