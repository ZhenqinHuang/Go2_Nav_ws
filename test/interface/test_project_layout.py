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
