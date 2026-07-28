from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NETWORK_DOC = ROOT / "docs" / "go2-control-network-and-console.md"
CHECKLIST = ROOT / "docs" / "go2-control-acceptance-checklist.md"
PACKAGE_README = ROOT / "src" / "Go2_control_gateway" / "README.md"


def read(path):
    assert path.is_file(), f"missing documentation: {path}"
    return path.read_text(encoding="utf-8")


def test_network_document_lists_every_device_ip_and_interface_role():
    document = read(NETWORK_DOC)
    for address in (
        "192.168.0.101",
        "192.168.123.5",
        "192.168.1.5",
        "192.168.123.18",
        "192.168.123.161",
        "192.168.1.158",
    ):
        assert address in document
    for interface in ("eth0", "eth1", "wlan0"):
        assert interface in document
    assert "默认路由" in document
    assert "MID360" in document


def test_document_explains_three_layer_control_and_fail_closed_protocol():
    document = read(NETWORK_DOC)

    assert "外载 Jetson" in document
    assert "内载计算机" in document
    assert "Go2 下位机" in document
    assert "/cmd_vel" in document
    assert "15000" in document and "15001" in document
    assert "Arm" in document
    assert "0.5" in document
    assert "watchdog" in document.lower()
    assert "旧令牌" in document
    assert "StopMove" in document


def test_console_and_operation_documentation_covers_required_workflow():
    document = read(NETWORK_DOC)

    assert "http://192.168.0.101:8080" in document
    assert "operator" in document
    assert "接管控制" in document
    assert "取消导航" in document
    assert "Nav2" in document
    assert "Disarm" in document
    assert "充电器" in document
    assert "松开" in document
    assert "关机" in document


def test_troubleshooting_acceptance_and_rollback_are_actionable():
    document = read(NETWORK_DOC)
    checklist = read(CHECKLIST)
    package = read(PACKAGE_README)

    assert "ip route get 192.168.123.161" in document
    assert "ping -I eth1 192.168.1.158" in document
    assert "GO2_CONTROL_BACKEND=direct-dds" in document
    assert "go2_gateway_disarm.sh" in document
    assert "go2_cmd_gateway" in checklist
    assert "坏 CRC" in checklist
    assert "实机" in checklist
    assert "暂未验证" in checklist
    assert "dry-run" in package
    assert "go2_console" in package


def test_top_level_readmes_link_to_delivery_document():
    root_readme = read(ROOT / "README.md")
    bringup_readme = read(ROOT / "src" / "Go2_bringup" / "README.md")

    assert "go2-control-network-and-console.md" in root_readme
    assert "go2_gateway_arm.sh" in bringup_readme
    assert "GO2_CONTROL_BACKEND" in bringup_readme
