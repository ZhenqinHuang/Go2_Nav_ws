import importlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def load_console():
    spec = importlib.util.find_spec("go2_control_gateway.console_core")
    if spec is None:
        pytest.fail("console_core module is missing")
    return importlib.import_module("go2_control_gateway.console_core")


def make_policy(module, clock, *, idle=10.0, absolute=30.0, tokens=None):
    values = iter(
        tokens
        or [
            "session-token-one-opaque",
            "csrf-token-one-opaque",
            "session-token-two-opaque",
            "csrf-token-two-opaque",
        ]
    )
    password_hash = module.hash_password(
        "correct horse battery staple",
        salt=b"0123456789abcdef",
        n=1024,
    )
    config = module.ConsolePolicyConfig(
        username="operator",
        password_hash=password_hash,
        session_idle_timeout_sec=idle,
        session_absolute_timeout_sec=absolute,
        lease_timeout_sec=2.0,
        manual_timeout_sec=0.2,
    )
    return module.ConsolePolicy(
        config=config,
        clock=clock,
        token_source=lambda: next(values),
    )


def login(policy):
    return policy.login("operator", "correct horse battery staple")


def test_scrypt_password_hash_verifies_without_storing_plaintext():
    module = load_console()
    encoded = module.hash_password(
        "correct horse battery staple",
        salt=b"0123456789abcdef",
        n=1024,
    )

    assert encoded.startswith("scrypt$")
    assert "correct horse battery staple" not in encoded
    assert module.verify_password("correct horse battery staple", encoded)
    assert not module.verify_password("wrong password", encoded)


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("wrong-user", "correct horse battery staple"),
        ("操作员", "correct horse battery staple"),
        ("operator", "wrong password"),
    ],
)
def test_login_uses_same_generic_error_for_bad_credentials(username, password):
    module = load_console()
    clock = FakeClock()
    policy = make_policy(module, clock)

    with pytest.raises(module.AuthenticationError) as error:
        policy.login(username, password)

    assert str(error.value) == "invalid credentials"


def test_sessions_are_opaque_unique_and_server_side():
    module = load_console()
    clock = FakeClock()
    policy = make_policy(module, clock)

    first = login(policy)
    second = login(policy)

    assert first.session_id != second.session_id
    assert first.csrf_token != second.csrf_token
    assert first.session_id != "operator"
    assert policy.authenticate(first.session_id).username == "operator"


def test_idle_and_absolute_session_expiration_release_control():
    module = load_console()
    clock = FakeClock()
    policy = make_policy(module, clock, idle=5.0, absolute=12.0)
    session = login(policy)
    assert policy.acquire_control(session.session_id)

    clock.advance(4.0)
    policy.authenticate(session.session_id)
    clock.advance(4.0)
    policy.authenticate(session.session_id)
    clock.advance(4.01)

    with pytest.raises(module.AuthenticationError):
        policy.authenticate(session.session_id)
    assert not policy.public_state()["control_lease_held"]


def test_only_one_session_can_hold_control_lease():
    module = load_console()
    clock = FakeClock()
    policy = make_policy(module, clock)
    first = login(policy)
    second = login(policy)

    assert policy.acquire_control(first.session_id)
    with pytest.raises(module.ControlLeaseError):
        policy.acquire_control(second.session_id)
    assert policy.acquire_control(first.session_id)


def test_logout_and_disconnect_release_lease_and_zero_manual_command():
    module = load_console()
    clock = FakeClock()
    policy = make_policy(module, clock)
    first = login(policy)
    assert policy.acquire_control(first.session_id)
    policy.submit_manual(first.session_id, 0.2, 0.0, 0.1)

    policy.disconnect(first.session_id)
    assert policy.current_manual_command() == (0.0, 0.0, 0.0)
    assert not policy.public_state()["control_lease_held"]

    assert policy.acquire_control(first.session_id)
    policy.logout(first.session_id)
    assert not policy.public_state()["control_lease_held"]
    with pytest.raises(module.AuthenticationError):
        policy.authenticate(first.session_id)


def test_nav2_active_rejects_manual_until_navigation_is_idle():
    module = load_console()
    clock = FakeClock()
    policy = make_policy(module, clock)
    session = login(policy)
    policy.acquire_control(session.session_id)
    policy.set_nav_active(True)

    with pytest.raises(module.ManualControlError) as error:
        policy.submit_manual(session.session_id, 0.2, 0.0, 0.0)
    assert "cancel navigation" in str(error.value).lower()

    policy.set_nav_active(False)
    assert policy.submit_manual(session.session_id, 0.2, 0.0, 0.0)


def test_manual_heartbeat_expiry_returns_zero_but_keeps_lease():
    module = load_console()
    clock = FakeClock()
    policy = make_policy(module, clock)
    session = login(policy)
    policy.acquire_control(session.session_id)

    policy.submit_manual(session.session_id, 0.2, 0.0, 0.1)
    assert policy.current_manual_command() == pytest.approx((0.2, 0.0, 0.1))
    clock.advance(0.21)
    assert policy.current_manual_command() == (0.0, 0.0, 0.0)
    assert policy.public_state()["control_lease_held"]


def test_authenticated_operator_can_disarm_without_control_lease():
    module = load_console()
    clock = FakeClock()
    policy = make_policy(module, clock)
    session = login(policy)

    assert policy.authorize_disarm(session.session_id)
    with pytest.raises(module.AuthenticationError):
        policy.authorize_disarm("not-a-session")


def test_public_state_never_exposes_hash_session_or_csrf_tokens():
    module = load_console()
    clock = FakeClock()
    policy = make_policy(module, clock)
    session = login(policy)
    policy.acquire_control(session.session_id)

    public_text = json.dumps(policy.public_state())

    assert policy.config.password_hash not in public_text
    assert session.session_id not in public_text
    assert session.csrf_token not in public_text
    assert "password" not in public_text.lower()
    assert "csrf" not in public_text.lower()
    assert "token" not in public_text.lower()
