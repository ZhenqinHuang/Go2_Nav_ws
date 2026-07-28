from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PACKAGE_ROOT / "go2_control_gateway" / "web"


def read(name):
    path = WEB_ROOT / name
    assert path.is_file(), f"missing web asset: {name}"
    return path.read_text(encoding="utf-8")


def test_page_contains_login_and_required_robot_status_fields():
    html = read("index.html")

    assert 'id="login-form"' in html
    assert 'autocomplete="username"' in html
    assert 'autocomplete="current-password"' in html
    for element_id in (
        "gateway-state",
        "arm-state",
        "nav-state",
        "battery-value",
        "mode-value",
        "velocity-value",
        "odometry-value",
    ):
        assert f'id="{element_id}"' in html


def test_page_has_arm_disarm_cancel_and_hold_to_run_controls():
    html = read("index.html")

    assert 'id="arm-button"' in html
    assert 'id="disarm-button"' in html
    assert 'id="cancel-nav-button"' in html
    for command in ("forward", "backward", "left", "right", "stop"):
        assert f'data-command="{command}"' in html
    assert 'id="manual-linear-speed"' in html
    assert 'id="manual-angular-speed"' in html


def test_controls_are_accessible_and_release_paths_force_stop():
    html = read("index.html")
    javascript = read("app.js")

    assert html.count("aria-label=") >= 10
    assert "pointerdown" in javascript
    assert "pointerup" in javascript
    assert "pointercancel" in javascript
    assert "keyup" in javascript
    assert "blur" in javascript
    assert "visibilitychange" in javascript
    assert "sendStop" in javascript
    assert "window.confirm" in javascript


def test_frontend_uses_only_authenticated_fixed_api_not_rosbridge():
    combined = "\n".join(
        [read("index.html"), read("app.js"), read("app.css")]
    )
    for endpoint in (
        "/api/login",
        "/api/control/acquire",
        "/api/arm",
        "/api/disarm",
        "/api/manual",
        "/api/navigation/cancel",
        "/ws/state",
    ):
        assert endpoint in combined
    forbidden = ("rosbridge", "ROSLIB", "ws://", "wss://", "/cmd_vel")
    assert not any(value in combined for value in forbidden)


def test_nav_active_state_disables_manual_controls_in_client_too():
    javascript = read("app.js")

    assert "navActive" in javascript
    assert "manual-control" in javascript
    assert "cancel-nav-button" in javascript
    assert "disabled" in javascript
