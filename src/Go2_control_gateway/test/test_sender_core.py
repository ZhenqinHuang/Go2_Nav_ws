from dataclasses import replace
import importlib
import importlib.util
import math
from pathlib import Path
import sys

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from go2_control_gateway.protocol import (  # noqa: E402
    AckFrame,
    ControlFlags,
    FaultReason,
    GatewayState,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def load_sender():
    spec = importlib.util.find_spec("go2_control_gateway.sender_core")
    if spec is None:
        pytest.fail("sender_core module is missing")
    return importlib.import_module("go2_control_gateway.sender_core")


def make_core(sender, clock, *, tokens=None, **config_overrides):
    values = iter(tokens or [201, 202, 203, 204])
    config = replace(
        sender.SenderConfig(localization_guard_enabled=False),
        **config_overrides,
    )
    return sender.SenderCore(
        config=config,
        clock=clock,
        token_source=lambda: next(values),
        session_id=101,
    )


def ack_for(packet, *, state=GatewayState.ARMED, sdk_code=0, fault=FaultReason.NONE):
    return AckFrame(
        session_id=packet.session_id,
        sequence=packet.sequence,
        arm_token=packet.arm_token,
        state=state,
        sdk_code=sdk_code,
        fault=fault,
        flags=0,
    )


def arm(core):
    token = core.request_arm()
    packet = core.next_packet()
    assert packet.flags == ControlFlags.ARM_REQUEST
    assert packet.arm_token == token
    core.handle_ack(ack_for(packet))
    assert core.is_armed
    return token


def test_process_starts_locked_and_only_emits_zero():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)

    packet = core.next_packet()

    assert not core.is_armed
    assert packet.flags == ControlFlags.NONE
    assert (packet.vx, packet.vy, packet.vyaw) == (0.0, 0.0, 0.0)


def test_arm_requires_matching_armed_ack():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)

    token = core.request_arm()
    packet = core.next_packet()
    wrong = replace(ack_for(packet), session_id=999)

    assert not core.handle_ack(wrong)
    assert not core.is_armed
    assert core.handle_ack(ack_for(packet))
    assert core.is_armed
    assert core.arm_token == token


def test_link_timeout_revokes_arm_and_requires_a_new_token():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock, tokens=[201, 201, 202])
    old_token = arm(core)
    core.set_nav_active(True)
    core.update_nav_cmd(0.2, 0.0, 0.0)

    clock.advance(0.51)
    packet = core.next_packet()

    assert not core.is_armed
    assert packet.flags == ControlFlags.NONE
    assert packet.vx == 0.0
    assert core.arm_token == 0
    assert core.request_arm() == 202
    assert old_token in core.revoked_tokens


def test_nav_cmd_timeout_stops_but_keeps_arm_when_ack_is_fresh():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)
    arm(core)
    core.set_nav_active(True)
    core.update_nav_cmd(0.3, 0.0, 0.0)
    moving = core.next_packet()
    clock.advance(0.40)
    core.handle_ack(ack_for(moving))
    clock.advance(0.21)

    stopped = core.next_packet()

    assert core.is_armed
    assert (stopped.vx, stopped.vy, stopped.vyaw) == (0.0, 0.0, 0.0)


def test_manual_commands_are_rejected_while_nav_is_active():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)
    arm(core)
    core.set_nav_active(True)

    accepted = core.update_manual_cmd(0.2, 0.0, 0.0)

    assert not accepted
    assert core.next_packet().vx == 0.0


def test_manual_command_requires_fresh_heartbeat_and_idle_nav():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock, manual_cmd_timeout_sec=0.20)
    arm(core)
    core.set_nav_active(False)

    assert core.update_manual_cmd(0.2, 0.0, 0.1)
    assert core.next_packet().vx == pytest.approx(0.2)
    clock.advance(0.21)
    assert core.next_packet().vx == 0.0
    assert core.is_armed


def test_velocity_is_finite_deadbanded_and_clamped_twice():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock, vyaw_smooth_alpha=1.0)
    arm(core)
    core.set_nav_active(True)

    core.update_nav_cmd(1.0, 0.5, -2.0)
    limited = core.next_packet()
    assert (limited.vx, limited.vy, limited.vyaw) == pytest.approx((0.6, 0.0, -1.4))

    core.update_nav_cmd(0.01, 0.0, -0.01)
    deadbanded = core.next_packet()
    assert (deadbanded.vx, deadbanded.vy, deadbanded.vyaw) == (0.0, 0.0, 0.0)

    assert not core.update_nav_cmd(math.nan, 0.0, 0.0)
    assert core.next_packet().vx == 0.0


def test_localization_guard_blocks_missing_and_stale_localization():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(
        sender,
        clock,
        localization_guard_enabled=True,
        localization_timeout_sec=1.5,
    )
    arm(core)
    core.set_nav_active(True)
    core.update_nav_cmd(0.2, 0.0, 0.0)
    assert core.next_packet().vx == 0.0

    core.update_localization(0.0, 0.0, 0.0)
    core.update_nav_cmd(0.2, 0.0, 0.0)
    moving = core.next_packet()
    assert moving.vx == pytest.approx(0.2)

    clock.advance(1.4)
    core.handle_ack(ack_for(moving))
    core.update_nav_cmd(0.2, 0.0, 0.0)
    clock.advance(0.11)
    assert core.next_packet().vx == 0.0
    assert core.is_armed


def test_localization_jump_pauses_motion_for_settle_window():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(
        sender,
        clock,
        localization_guard_enabled=True,
        correction_pause_sec=0.8,
        correction_pause_delta_xy=0.5,
    )
    arm(core)
    core.set_nav_active(True)
    core.update_localization(0.0, 0.0, 0.0)
    core.update_nav_cmd(0.2, 0.0, 0.0)
    moving = core.next_packet()
    assert moving.vx == pytest.approx(0.2)

    core.update_localization(0.6, 0.0, 0.0)
    core.update_nav_cmd(0.2, 0.0, 0.0)
    assert core.next_packet().vx == 0.0
    clock.advance(0.79)
    core.handle_ack(ack_for(moving))
    core.update_nav_cmd(0.2, 0.0, 0.0)
    assert core.next_packet().vx == 0.0
    clock.advance(0.02)
    assert core.next_packet().vx == pytest.approx(0.2)


def test_sequence_increases_monotonically_within_session():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)

    packets = [core.next_packet() for _ in range(3)]

    assert [packet.session_id for packet in packets] == [101, 101, 101]
    assert [packet.sequence for packet in packets] == [1, 2, 3]


def test_arm_confirmation_timeout_revokes_token_and_stays_stopped():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)
    token = core.request_arm()
    assert core.next_packet().flags == ControlFlags.ARM_REQUEST

    clock.advance(1.01)
    packet = core.next_packet()

    assert packet.flags == ControlFlags.NONE
    assert packet.arm_token == 0
    assert (packet.vx, packet.vy, packet.vyaw) == (0.0, 0.0, 0.0)
    assert token in core.revoked_tokens


def test_explicit_disarm_sends_zero_until_matching_locked_ack():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)
    token = arm(core)
    core.set_nav_active(True)
    core.update_nav_cmd(0.2, 0.0, 0.0)
    core.request_disarm()

    packet = core.next_packet()
    assert not core.is_armed
    assert packet.flags == ControlFlags.DISARM
    assert packet.arm_token == token
    assert (packet.vx, packet.vy, packet.vyaw) == (0.0, 0.0, 0.0)

    assert core.handle_ack(ack_for(packet, state=GatewayState.LOCKED))
    locked = core.next_packet()
    assert locked.flags == ControlFlags.NONE
    assert locked.arm_token == 0
    assert token in core.revoked_tokens


def test_sdk_error_ack_fails_closed_immediately():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)
    token = arm(core)
    packet = core.next_packet()

    assert core.handle_ack(
        ack_for(
            packet,
            state=GatewayState.FAULT,
            sdk_code=-1,
            fault=FaultReason.SDK,
        )
    )
    stopped = core.next_packet()
    assert not core.is_armed
    assert stopped.arm_token == 0
    assert stopped.vx == 0.0
    assert token in core.revoked_tokens


def test_yaw_command_uses_configured_exponential_smoothing():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock, vyaw_smooth_alpha=0.5)
    arm(core)
    core.set_nav_active(True)

    assert core.update_nav_cmd(0.0, 0.0, 1.0)
    assert core.next_packet().vyaw == pytest.approx(0.5)
    assert core.update_nav_cmd(0.0, 0.0, 1.0)
    assert core.next_packet().vyaw == pytest.approx(0.75)
