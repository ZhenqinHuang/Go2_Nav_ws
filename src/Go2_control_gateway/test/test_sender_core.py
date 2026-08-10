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
    AckFlags,
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


def make_core(sender, clock, **config_overrides):
    config = replace(
        sender.SenderConfig(localization_guard_enabled=False),
        **config_overrides,
    )
    return sender.SenderCore(config=config, clock=clock, session_id=101)


def ack_for(packet, *, sdk_code=0, fault=FaultReason.NONE, flags=0):
    return AckFrame(
        session_id=packet.session_id,
        sequence=packet.sequence,
        arm_token=0,
        state=GatewayState.LOCKED,
        sdk_code=sdk_code,
        fault=fault,
        flags=flags,
    )


def mark_link_ready(core):
    packet = core.next_packet()
    assert packet.flags == ControlFlags.NONE
    assert packet.arm_token == 0
    assert core.handle_ack(ack_for(packet))


def test_process_starts_with_token_zero_and_only_emits_zero():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)

    packet = core.next_packet()

    assert packet.flags == ControlFlags.NONE
    assert packet.arm_token == 0
    assert (packet.vx, packet.vy, packet.vyaw) == (0.0, 0.0, 0.0)
    assert not core.control_ready


def test_manual_command_flows_after_link_ack_without_arm():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)
    mark_link_ready(core)

    assert core.update_manual_cmd(0.2, 0.0, 0.1)
    packet = core.next_packet()

    assert packet.flags == ControlFlags.NONE
    assert packet.arm_token == 0
    assert packet.vx == pytest.approx(0.2)
    assert packet.vyaw == pytest.approx(0.035)


def test_nav_command_flows_after_link_ack_without_arm():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)
    mark_link_ready(core)
    core.set_nav_active(True)

    assert core.update_nav_cmd(0.3, 0.0, 0.0)
    assert core.next_packet().vx == pytest.approx(0.3)


def test_matching_locked_ack_is_required_for_link_ready():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)
    packet = core.next_packet()

    assert not core.handle_ack(replace(ack_for(packet), session_id=999))
    assert not core.handle_ack(replace(ack_for(packet), arm_token=7))
    assert not core.handle_ack(
        replace(ack_for(packet), state=GatewayState.ARMED)
    )
    assert core.handle_ack(ack_for(packet))
    assert core.control_ready


def test_ack_timeout_clears_commands_and_requires_fresh_command():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock, ack_timeout_sec=0.5)
    mark_link_ready(core)
    assert core.update_manual_cmd(0.2, 0.0, 0.0)
    assert core.next_packet().vx == pytest.approx(0.2)

    clock.advance(0.51)
    assert core.next_packet().vx == 0.0
    assert not core.control_ready

    mark_link_ready(core)
    assert core.next_packet().vx == 0.0
    assert core.update_manual_cmd(0.2, 0.0, 0.0)
    assert core.next_packet().vx == pytest.approx(0.2)


def test_fault_ack_clears_pending_velocity():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)
    mark_link_ready(core)
    core.update_manual_cmd(0.2, 0.0, 0.0)
    moving = core.next_packet()

    assert core.handle_ack(
        ack_for(moving, sdk_code=-1, fault=FaultReason.SDK)
    )
    assert core.next_packet().vx == 0.0


def test_nav_cmd_timeout_stops_without_arm_state():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)
    mark_link_ready(core)
    core.set_nav_active(True)
    core.update_nav_cmd(0.3, 0.0, 0.0)
    moving = core.next_packet()
    clock.advance(0.40)
    core.handle_ack(ack_for(moving))
    clock.advance(0.21)

    assert core.next_packet().vx == 0.0


def test_manual_commands_are_rejected_while_nav_is_active():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)
    mark_link_ready(core)
    core.set_nav_active(True)

    assert not core.update_manual_cmd(0.2, 0.0, 0.0)
    assert core.next_packet().vx == 0.0


def test_manual_command_requires_fresh_heartbeat_and_idle_nav():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock, manual_cmd_timeout_sec=0.20)
    mark_link_ready(core)

    assert core.update_manual_cmd(0.2, 0.0, 0.1)
    assert core.next_packet().vx == pytest.approx(0.2)
    clock.advance(0.21)
    assert core.next_packet().vx == 0.0


def test_velocity_is_finite_deadbanded_and_clamped_twice():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock, vyaw_smooth_alpha=1.0)
    mark_link_ready(core)
    core.set_nav_active(True)

    core.update_nav_cmd(1.0, 0.5, -2.0)
    limited = core.next_packet()
    assert (limited.vx, limited.vy, limited.vyaw) == pytest.approx(
        (0.6, 0.0, -1.4)
    )

    core.update_nav_cmd(0.01, 0.0, -0.01)
    deadbanded = core.next_packet()
    assert (deadbanded.vx, deadbanded.vy, deadbanded.vyaw) == (
        0.0,
        0.0,
        0.0,
    )

    assert not core.update_nav_cmd(math.nan, 0.0, 0.0)
    assert core.next_packet().vx == 0.0


def test_localization_guard_blocks_missing_stale_and_jump():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(
        sender,
        clock,
        localization_guard_enabled=True,
        localization_timeout_sec=1.5,
        correction_pause_sec=0.8,
        correction_pause_delta_xy=0.5,
    )
    mark_link_ready(core)
    core.set_nav_active(True)
    core.update_nav_cmd(0.2, 0.0, 0.0)
    assert core.next_packet().vx == 0.0

    core.update_localization(0.0, 0.0, 0.0)
    core.update_nav_cmd(0.2, 0.0, 0.0)
    moving = core.next_packet()
    assert moving.vx == pytest.approx(0.2)

    core.update_localization(0.6, 0.0, 0.0)
    core.update_nav_cmd(0.2, 0.0, 0.0)
    assert core.next_packet().vx == 0.0
    clock.advance(0.81)
    core.handle_ack(ack_for(moving))
    core.update_nav_cmd(0.2, 0.0, 0.0)
    assert core.next_packet().vx == pytest.approx(0.2)

    clock.advance(1.51)
    assert core.next_packet().vx == 0.0


def test_sequence_increases_monotonically_within_session():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)

    packets = [core.next_packet() for _ in range(3)]

    assert [packet.session_id for packet in packets] == [101, 101, 101]
    assert [packet.sequence for packet in packets] == [1, 2, 3]
    assert all(packet.arm_token == 0 for packet in packets)
    assert all(packet.flags == ControlFlags.NONE for packet in packets)


def test_yaw_command_uses_configured_exponential_smoothing():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock, vyaw_smooth_alpha=0.5)
    mark_link_ready(core)
    core.set_nav_active(True)

    assert core.update_nav_cmd(0.0, 0.0, 1.0)
    assert core.next_packet().vyaw == pytest.approx(0.5)
    assert core.update_nav_cmd(0.0, 0.0, 1.0)
    assert core.next_packet().vyaw == pytest.approx(0.75)


def test_emergency_stop_latches_and_rejects_new_velocity_until_acknowledged_reset():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)
    mark_link_ready(core)
    assert core.update_manual_cmd(0.2, 0.0, 0.0)
    assert core.next_packet().vx == pytest.approx(0.2)

    assert core.request_emergency_stop()
    stop_packet = core.next_packet()
    assert stop_packet.flags == ControlFlags.EMERGENCY_STOP
    assert (stop_packet.vx, stop_packet.vy, stop_packet.vyaw) == (0.0, 0.0, 0.0)
    assert core.estop_latched
    assert not core.update_manual_cmd(0.2, 0.0, 0.0)
    assert core.handle_ack(
        ack_for(
            stop_packet,
            fault=FaultReason.ESTOP,
            flags=AckFlags.ESTOP_LATCHED | AckFlags.COMMAND_ACCEPTED,
        )
    )

    assert core.request_reset_emergency_stop()
    reset_packet = core.next_packet()
    assert reset_packet.flags == ControlFlags.RESET_ESTOP
    assert core.handle_ack(
        ack_for(reset_packet, flags=AckFlags.COMMAND_ACCEPTED)
    )
    assert not core.estop_latched
    assert core.update_manual_cmd(0.2, 0.0, 0.0)


def test_estop_reset_requires_idle_nav_fresh_link_and_localization():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(
        sender,
        clock,
        localization_guard_enabled=True,
        localization_timeout_sec=0.5,
    )
    core.request_emergency_stop()
    assert not core.request_reset_emergency_stop()

    stop_packet = core.next_packet()
    assert core.handle_ack(
        ack_for(
            stop_packet,
            fault=FaultReason.ESTOP,
            flags=AckFlags.ESTOP_LATCHED | AckFlags.COMMAND_ACCEPTED,
        )
    )
    assert not core.request_reset_emergency_stop()
    core.update_localization(0.0, 0.0, 0.0)
    core.set_nav_active(True)
    assert not core.request_reset_emergency_stop()
    core.set_nav_active(False)
    assert core.request_reset_emergency_stop()


def test_posture_commands_require_zero_speed_idle_nav_and_internal_ack():
    sender = load_sender()
    clock = FakeClock()
    core = make_core(sender, clock)
    mark_link_ready(core)

    core.set_nav_active(True)
    assert not core.request_posture("stand")
    core.set_nav_active(False)
    assert core.request_posture("stand")
    stand_packet = core.next_packet()
    assert stand_packet.flags == ControlFlags.STAND
    assert core.handle_ack(
        ack_for(
            stand_packet,
            flags=AckFlags.COMMAND_ACCEPTED | AckFlags.POSTURE_STANDING,
        )
    )
    assert core.posture == "standing"

    assert core.request_posture("lie")
    lie_packet = core.next_packet()
    assert lie_packet.flags == ControlFlags.LIE
    assert core.handle_ack(
        ack_for(
            lie_packet,
            flags=AckFlags.COMMAND_ACCEPTED | AckFlags.POSTURE_LYING,
        )
    )
    assert core.posture == "lying"
