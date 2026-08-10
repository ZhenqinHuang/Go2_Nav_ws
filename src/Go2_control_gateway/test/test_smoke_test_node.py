from pathlib import Path
import importlib
import sys

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))


def test_cli_parses_explicit_confirmation_and_bounded_motion():
    module = importlib.import_module("go2_control_gateway.smoke_test_node")

    config = module.parse_smoke_test_args(
        ["--confirm-safe", "--vx", "0.2", "--duration", "1.5"]
    )

    assert config.confirm_safe is True
    assert config.vx == 0.2
    assert config.duration_sec == 1.5


def test_cli_defaults_to_verified_minimum_walking_pulse():
    module = importlib.import_module("go2_control_gateway.smoke_test_node")

    config = module.parse_smoke_test_args(["--confirm-safe"])

    assert config.vx == 0.2
    assert config.duration_sec == 2.0


def test_package_installs_guarded_smoke_test_entry_point():
    setup_text = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")

    assert (
        "go2_motion_smoke_test = "
        "go2_control_gateway.smoke_test_node:main"
    ) in setup_text


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def wait(self, seconds):
        self.now += seconds


class FakeAdapter:
    def __init__(self, states):
        self.states = list(states)
        self.calls = 0

    def get_state(self):
        self.calls += 1
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]


def test_waits_for_first_fresh_gateway_sample_instead_of_fixed_sleep():
    module = importlib.import_module("go2_control_gateway.smoke_test_node")
    clock = FakeClock()
    adapter = FakeAdapter(
        [
            {
                "gateway_link": "offline",
                "last_ack_age_sec": None,
            },
            {
                "gateway_link": "offline",
                "last_ack_age_sec": None,
            },
            {
                "gateway_link": "online",
                "last_ack_age_sec": 0.05,
            },
        ]
    )

    state = module.wait_for_initial_status(
        adapter,
        timeout_sec=5.0,
        clock=clock,
        waiter=clock.wait,
    )

    assert state["gateway_link"] == "online"
    assert adapter.calls == 3
    assert clock.now == pytest.approx(0.1)


def test_initial_status_wait_has_a_bounded_timeout():
    module = importlib.import_module("go2_control_gateway.smoke_test_node")
    clock = FakeClock()
    adapter = FakeAdapter(
        [{"gateway_link": "offline", "last_ack_age_sec": None}]
    )

    with pytest.raises(module.SmokeTestAbort, match="status sample"):
        module.wait_for_initial_status(
            adapter,
            timeout_sec=0.1,
            clock=clock,
            waiter=clock.wait,
        )
