from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_operator_documentation_exists():
    required = {
        "architecture.md",
        "deployment.md",
        "mapping.md",
        "operations.md",
        "troubleshooting.md",
    }

    assert required <= {path.name for path in (ROOT / "docs").glob("*.md")}


def test_jetson_guardrails_are_published():
    document = ROOT / "docs" / "jetson-development-guardrails.md"
    text = document.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required = {
        "192.168.0.101",
        "192.168.123.5",
        "192.168.1.5",
        "map -> odom -> base_link",
        "go2-motion-sender.service",
        "map_manifest.yaml",
        "emergency-stop",
        "staging",
    }

    assert document.name in readme
    assert all(value in text for value in required)


def test_daily_work_log_is_published():
    document = ROOT / "docs" / "work-log-2026-08-10.md"
    text = document.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required = {
        "管理摘要",
        "技术明细",
        "FAST-LIO2",
        "go2-motion-sender.service",
        "a9e7854",
        "103 passed",
        "70 passed",
        "25 passed",
        "staging",
        "现网尚未切换",
        "实机运动尚未授权",
    }

    assert document.name in readme
    assert all(value in text for value in required)


def test_integrated_packages_have_stable_locations():
    required = {
        "Go2_bringup",
        "Go2_Slam",
        "Go2_localization",
        "Go2_perception",
        "Go2_nav2",
        "Go2_control_gateway",
        "Go2_web_console",
        "Go2_web_bridge",
        "Go2_time_sync",
    }

    assert required <= {path.name for path in (ROOT / "src").iterdir() if path.is_dir()}


def test_root_entry_points_exist():
    required = {
        "install.sh",
        "start_mapping.sh",
        "start_navigation.sh",
        "check_system.sh",
        "stop_all.sh",
    }

    scripts = ROOT / "scripts"
    assert scripts.is_dir()
    assert required <= {path.name for path in scripts.glob("*.sh")}


def test_canonical_map_bundle_files_exist():
    required = {
        "MID360.pcd",
        "MID360_map.pgm",
        "MID360_map.yaml",
        "map_manifest.yaml",
    }

    assert required <= {path.name for path in (ROOT / "maps").iterdir() if path.is_file()}


def test_non_active_map_archive_is_documented():
    archive = ROOT / "maps" / "archive"
    assert archive.is_dir()
    assert (archive / "README.md").is_file()


def test_top_level_test_groups_are_documented():
    for group in ("interface", "safety", "smoke"):
        directory = ROOT / "test" / group
        assert directory.is_dir()

    assert (ROOT / "test" / "safety" / "README.md").is_file()
    assert (ROOT / "test" / "smoke" / "README.md").is_file()


def test_source_packages_do_not_embed_duplicate_active_maps():
    localization = ROOT / "src/Go2_localization"
    assert not list((localization / "PCD").glob("*.pcd"))
    assert not list((localization / "fast_lio_localization_ros2/PCD").glob("*.pcd"))
    assert not (ROOT / "MID360_map.pgm").exists()


def test_obsolete_bringup_entry_points_are_absent():
    bringup = ROOT / "src/Go2_bringup"
    obsolete = {
        "build_map.sh",
        "check_nav2_ready.sh",
        "go2_autostart.sh",
        "go2_nav_start.sh",
        "run_nav2.sh",
        "run_robot_web.sh",
        "go2-autostart.service",
    }
    assert not (obsolete & {path.name for path in bringup.iterdir()})


def test_frontend_public_assets_only_contain_runtime_files():
    public = ROOT / "src/Go2_web_console/frontend/public"
    assert {path.name for path in public.iterdir()} == {"icon.svg"}
    screenshots = ROOT / "src/Go2_web_console/docs/screenshots"
    assert len(list(screenshots.glob("*.png"))) == 9
    production = ROOT / "src/Go2_web_console/go2_web_console/web"
    assert not list(production.glob("*.png"))
    assert not (production / "robot_image.jpg").exists()
    assert not (production / "vite.svg").exists()


def test_local_codex_backup_artifacts_are_not_delivered():
    assert not (ROOT / ".codex").exists()
    assert not list((ROOT / ".codex_backups").glob("**/*.*"))
