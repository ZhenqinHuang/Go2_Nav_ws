from pathlib import Path
import importlib.util
import sys


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))


def test_package_exposes_runtime_directories():
    spec = importlib.util.find_spec("go2_control_gateway")
    assert spec is not None, "go2_control_gateway package is missing"

    import go2_control_gateway as gateway

    module_root = Path(gateway.__file__).resolve().parent

    assert (module_root / "web").is_dir()
    assert (PACKAGE_ROOT / "config").is_dir()
