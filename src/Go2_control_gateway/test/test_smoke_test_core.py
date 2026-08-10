from pathlib import Path
import sys

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from go2_control_gateway.smoke_test_core import (  # noqa: E402
    SmokeTestAbort,
    SmokeTestConfig,
    run_smoke_test,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def wait(self, seconds):
        self.now += seconds


class FakeIo:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.commands = []

    def get_state(self):
        if len(self.statuses) > 1:
            return self.statuses.pop(0)
        return self.statuses[0]

    def manual_command(self, vx, vy, vyaw):
        self.commands.append((vx, vy, vyaw))

def status(*, link="online", ack_age=0.05, nav="IDLE"):
    return {
        "gateway_link": link,
        "last_ack_age_sec": ack_age,
        "nav2_status": nav,
    }


def test_confirmation_is_mandatory_before_any_robot_operation():
    io = FakeIo([status()])

    with pytest.raises(ValueError, match="confirm-safe"):
        run_smoke_test(io, SmokeTestConfig(confirm_safe=False))

    assert io.commands == []


@pytest.mark.parametrize(
    "config",
    [
        SmokeTestConfig(confirm_safe=True, vx=0.19),
        SmokeTestConfig(confirm_safe=True, vx=-0.19),
        SmokeTestConfig(confirm_safe=True, vx=0.0),
        SmokeTestConfig(confirm_safe=True, vx=0.21),
        SmokeTestConfig(confirm_safe=True, vx=-0.21),
        SmokeTestConfig(confirm_safe=True, duration_sec=2.01),
        SmokeTestConfig(confirm_safe=True, duration_sec=0.0),
    ],
)
def test_verified_motion_envelope_rejects_ineffective_speed_or_unsafe_limits(
    config,
):
    with pytest.raises(ValueError):
        run_smoke_test(FakeIo([status()]), config)


@pytest.mark.parametrize(
    "unsafe",
    [
        status(link="offline"),
        status(nav="EXECUTING"),
        status(ack_age=0.41),
    ],
)
def test_preflight_requires_online_idle_and_fresh_ack(unsafe):
    io = FakeIo([unsafe])

    with pytest.raises(SmokeTestAbort):
        run_smoke_test(io, SmokeTestConfig(confirm_safe=True))

    assert io.commands == []


def test_success_is_bounded_and_always_finishes_with_repeated_zero():
    clock = FakeClock()
    io = FakeIo(
        [
            status(),
            status(),
            status(),
        ]
    )

    run_smoke_test(
        io,
        SmokeTestConfig(
            confirm_safe=True,
            vx=0.2,
            duration_sec=0.2,
            command_hz=20.0,
        ),
        clock=clock,
        waiter=clock.wait,
    )

    moving = [command for command in io.commands if command[0] != 0.0]
    assert moving
    assert all(command == (0.2, 0.0, 0.0) for command in moving)
    assert io.commands[-3:] == [(0.0, 0.0, 0.0)] * 3


def test_stale_ack_during_motion_aborts_and_still_stops():
    clock = FakeClock()
    io = FakeIo(
        [
            status(),
            status(),
            status(ack_age=0.41),
        ]
    )

    with pytest.raises(SmokeTestAbort, match="ACK"):
        run_smoke_test(
            io,
            SmokeTestConfig(
                confirm_safe=True,
                vx=0.2,
                duration_sec=0.5,
                command_hz=20.0,
            ),
            clock=clock,
            waiter=clock.wait,
        )

    assert io.commands[-3:] == [(0.0, 0.0, 0.0)] * 3
