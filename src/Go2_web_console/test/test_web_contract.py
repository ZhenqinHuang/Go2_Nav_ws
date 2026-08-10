import io
from pathlib import Path
import subprocess
import tarfile


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = PACKAGE_ROOT / "frontend" / "src"
WEB_ROOT = PACKAGE_ROOT / "go2_web_console" / "web"


def source(relative):
    path = FRONTEND_SRC / relative
    assert path.is_file(), f"missing frontend source: {relative}"
    return path.read_text(encoding="utf-8")


def all_typescript():
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in FRONTEND_SRC.rglob("*")
        if path.suffix in {".ts", ".tsx"}
    )


def test_react_shell_contains_authenticated_login_map_and_go2_panel():
    app = source("App.tsx")
    login = source("components/Go2Login.tsx")
    panel = source("components/Go2ControlPanel.tsx")

    assert "Go2Login" in app
    assert "MapView" in app
    assert "Go2ControlPanel" in app
    assert 'autoComplete="username"' in login
    assert 'autoComplete="current-password"' in login
    for label in ("网关", "速度通路", "Nav2", "控制权", "电量", "里程计"):
        assert label in panel


def test_map_editor_imports_from_jetson_library_and_keeps_local_zip_picker():
    editor = source("components/MapEditor.tsx")
    dialog = source("components/MapImportDialog.tsx")
    client = source("api/consoleClient.ts")

    assert "MapImportDialog" in editor
    assert "Jetson 地图库" in dialog
    assert "载入选中地图" in dialog
    assert "从电脑选择 ZIP" in dialog
    assert 'accept=".zip"' in editor
    assert "/api/mapping/maps/" in client


def test_mapping_panel_contains_a_read_only_live_2d_preview():
    app = source("App.tsx")
    panel = source("components/MappingPanel.tsx")
    preview = source("components/LiveMappingPreview.tsx")
    connection = source("utils/RosbridgeConnection.ts")

    assert "connection={connection}" in app
    assert "LiveMappingPreview" in panel
    for label in (
        "实时 2D 预览",
        "暂停显示",
        "最低高度",
        "最高高度",
        "行走轨迹",
        "此画面仅用于预览",
    ):
        assert label in preview
    assert "sensor_msgs/PointCloud2" in preview
    assert "callbacks: Set" in connection


def test_console_uses_shared_map_with_separate_operating_workspaces():
    app = source("App.tsx")
    chrome = source("components/WorkspaceChrome.tsx")
    map_view = source("components/MapView.tsx")

    assert "WorkspaceChrome" in app
    assert "workspaceMode" in app
    for mode in ("control", "navigation", "mapping", "maps"):
        assert f"id: '{mode}'" in chrome
    for label in ("控制", "导航", "建图", "地图", "Go2", "雷达", "急停", "设置"):
        assert label in chrome
    assert "navigation-workspace-panel" in map_view
    assert "workspaceMode === 'maps'" in map_view


def test_hold_to_run_has_all_release_and_fail_closed_paths():
    panel = source("components/Go2ControlPanel.tsx")

    for event in (
        "onPointerDown",
        "onPointerUp",
        "onPointerCancel",
        "onPointerLeave",
        "onLostPointerCapture",
        "keyup",
        "blur",
        "visibilitychange",
    ):
        assert event in panel
    assert "stopManual" in panel
    assert "isNavActive" in panel
    assert "manualEnabled" in panel


def test_keyboard_control_has_explicit_safety_switch_and_fixed_shortcuts():
    panel = source("components/Go2ControlPanel.tsx")

    assert "Web 手动控制" in panel
    assert 'role="switch"' in panel
    for key in ("q:", "w:", "e:", "a:", "s:", "d:"):
        assert key in panel
    assert "event.code === 'Space'" in panel
    assert "key === 'f'" in panel
    assert "key === 'p'" in panel
    assert "recoveryStand" in panel


def test_manual_press_is_not_delayed_by_a_zero_command_round_trip():
    panel = source("components/Go2ControlPanel.tsx")
    begin_manual = panel.split("const beginManual", 1)[1].split(
        "useEffect(() =>", 1
    )[0]

    assert "await stopManual()" not in begin_manual
    assert "clearManualTimer()" in begin_manual


def test_control_does_not_offer_lateral_motion_rejected_by_verified_gateway():
    panel = source("components/Go2ControlPanel.tsx")
    policy = source("components/controlPolicy.ts")

    assert 'label="左移"' not in panel
    assert 'label="右移"' not in panel
    assert "strafe-left" not in policy
    assert "strafe-right" not in policy


def test_go2_control_stays_mounted_across_workspaces_for_global_keyboard_control():
    app = source("App.tsx")
    panel = source("components/Go2ControlPanel.tsx")
    styles = source("components/Go2ControlPanel.css")

    assert "<Go2ControlPanel" in app
    assert "visible={workspaceMode === 'control'}" in app
    assert "workspaceMode === 'control' && (\n          <Go2ControlPanel" not in app
    assert "docked?: boolean" in panel
    assert "visible?: boolean" in panel
    assert "webManualEnabled: boolean" in panel
    assert "onWebManualEnabledChange" in panel
    assert "go2-control-panel ${docked ? 'docked'" in panel
    assert "workspace-hidden" in panel
    assert ".go2-control-panel.docked" in styles
    assert ".go2-control-panel.workspace-hidden" in styles
    assert "right: 16px" in styles
    # The legacy floating version remains available for compatibility.
    assert "aria-expanded" in panel
    assert "go2-control-toggle" in panel
    assert ".go2-control-panel.collapsed" in styles


def test_global_statusbar_shows_battery_and_keyboard_control_state():
    chrome = source("components/WorkspaceChrome.tsx")

    assert 'label="电量"' in chrome
    assert "state?.battery_percent" in chrome
    assert 'label="键盘"' in chrome
    assert "全局开启" in chrome
    assert "关闭键控" in chrome


def test_control_operations_use_only_fixed_same_origin_api():
    client = source("api/consoleClient.ts")
    combined = all_typescript()

    for endpoint in (
        "/api/login",
        "/api/control/acquire",
        "/api/manual",
        "/api/stand-up",
        "/api/stand-down",
        "/api/recovery-stand",
        "/api/emergency-stop",
        "/api/navigation/goal",
        "/api/navigation/waypoints",
        "/api/navigation/cancel",
        "/api/navigation/system/status",
        "/api/navigation/system/speed",
        "/api/navigation/system/start",
        "/api/navigation/system/stop",
        "/api/localization/initialpose",
        "/ws/state",
        "/ws/ros",
    ):
        assert endpoint in client
    assert "/api/arm" not in client
    assert "/api/disarm" not in client
    assert ".publish(" not in combined
    assert ".advertise(" not in combined
    assert "callService(" not in combined
    assert "sendGoal(" not in combined


def test_manual_http_api_reaches_the_real_ros_velocity_topic():
    client = source("api/consoleClient.ts")
    server = (PACKAGE_ROOT / "go2_web_console" / "console_server.py").read_text(
        encoding="utf-8"
    )
    adapter = (PACKAGE_ROOT / "go2_web_console" / "ros_adapter.py").read_text(
        encoding="utf-8"
    )

    assert "return this.mutate('/api/manual', command)" in client
    assert 'app.router.add_post("/api/manual", manual)' in server
    assert 'Twist, "/go2/manual_cmd_vel", 10' in adapter
    assert "self._manual_publisher.publish(message)" in adapter


def test_navigation_visualization_and_editor_components_are_retained():
    map_view = source("components/MapView.tsx")

    for component in (
        "LayerSettingsPanel",
        "MapEditor",
        "NavigationPanel",
        "TaskManagementPanel",
        "SystemLogPanel",
        "TopoPointInfoPanel",
        "NavigationSystemPanel",
    ):
        assert component in map_view
    assert "navigateToPose" in map_view
    assert "navigateThroughPoses" in map_view
    assert "setInitialPose" in map_view


def test_navigation_system_requires_a_paired_map_and_reports_readiness():
    panel = source("components/NavigationSystemPanel.tsx")
    client = source("api/consoleClient.ts")

    for label in (
        "定位与 Nav2",
        "选择配对地图后启动",
        "MID360S",
        "运动网关",
        "TF 链",
        "Nav2 节点",
        "导航 Action",
    ):
        assert label in panel
    assert "available_maps" in panel
    assert "navigationSystem?.ready" in source("components/MapView.tsx")
    assert "/api/navigation/system/start" in client
    assert "/api/navigation/system/speed" in client
    assert "导航速度" in panel
    assert "应用速度" in panel
    assert "重定位确认" in panel
    assert "navigationSystem?.stack_ready" in source("components/MapView.tsx")


def test_live_cloud_never_falls_back_to_false_map_coordinates():
    point_cloud = source("components/layers/PointCloudLayer.tsx")
    layer_configs = source("constants/layerConfigs.ts")

    assert "topic: '/cur_scan_in_map'" in layer_configs
    assert "hiding cloud until transform is valid" in point_cloud
    assert "return;" in point_cloud


def test_navigation_visuals_use_thick_paths_and_directional_robot_marker():
    path_layer = source("components/layers/PathLayer.tsx")
    robot_layer = source("components/layers/RobotLayer.tsx")
    layer_configs = source("constants/layerConfigs.ts")

    assert "Line2" in path_layer
    assert "LineMaterial" in path_layer
    assert "Math.max" in path_layer
    assert "lineWidth: 6" in layer_configs
    assert "go2_heading_marker" in robot_layer
    assert "ROS base_link uses +X as forward" in robot_layer
    assert "ShapeGeometry" in robot_layer


def test_production_bundle_is_hashed_and_contains_console_endpoints():
    index = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (WEB_ROOT / "assets").glob("*.js")
    )

    assert '<div id="root"></div>' in index
    assert "/assets/" in index
    assert "/api/navigation/goal" in javascript
    assert "/api/navigation/system/start" in javascript
    assert "/api/manual" in javascript
    assert "/ws/ros" in javascript


def test_linux_deployment_files_are_forced_to_lf():
    attributes = (PACKAGE_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in attributes
    assert "*.service text eol=lf" in attributes

    deploy_files = [
        *PACKAGE_ROOT.glob("scripts/*.sh"),
        *PACKAGE_ROOT.glob("systemd/*.service"),
    ]
    assert deploy_files
    if (PACKAGE_ROOT / ".git").exists():
        archive = subprocess.check_output(
            ["git", "archive", "--format=tar", "HEAD"],
            cwd=PACKAGE_ROOT,
        )
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            contents = {
                str(path.relative_to(PACKAGE_ROOT)).replace("\\", "/"):
                bundle.extractfile(
                    str(path.relative_to(PACKAGE_ROOT)).replace("\\", "/")
                ).read()
                for path in deploy_files
            }
    else:
        contents = {
            str(path.relative_to(PACKAGE_ROOT)): path.read_bytes()
            for path in deploy_files
        }
    for relative_path, content in contents.items():
        assert b"\r" not in content, f"{relative_path} contains CRLF"


def test_frontend_installer_uses_verified_bundle_when_jetson_has_no_node():
    build_script = (PACKAGE_ROOT / "scripts" / "build_frontend.sh").read_text(
        encoding="utf-8"
    )

    assert "command -v npm" in build_script
    assert "production bundle already present; skipping target build" in build_script
    assert "npm is unavailable and production bundle is incomplete" in build_script
