from dataclasses import replace
import importlib
import importlib.util
import math
from pathlib import Path
import sys

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

CONTROL_GOLDEN_HEX = (
    "4732475700010001003800000102030405060708"
    "0000000000000009000000000000000a00000001"
    "3e4ccccd00000000be99999a473d1b0a"
)
ACK_GOLDEN_HEX = (
    "4732475700010002003800000102030405060708"
    "0000000000000009000000000000000a00000002"
    "000000000000000000000000704b9c8c"
)


def load_protocol():
    spec = importlib.util.find_spec("go2_control_gateway.protocol")
    if spec is None:
        pytest.fail("protocol module is missing")
    return importlib.import_module("go2_control_gateway.protocol")


def valid_control(protocol, **overrides):
    frame = protocol.ControlFrame(
        session_id=0x0102030405060708,
        sequence=9,
        arm_token=10,
        flags=protocol.ControlFlags.ARM_REQUEST,
        vx=0.2,
        vy=0.0,
        vyaw=-0.3,
    )
    return replace(frame, **overrides)


def valid_ack(protocol, **overrides):
    frame = protocol.AckFrame(
        session_id=0x0102030405060708,
        sequence=9,
        arm_token=10,
        state=protocol.GatewayState.ARMED,
        sdk_code=0,
        fault=protocol.FaultReason.NONE,
        flags=0,
    )
    return replace(frame, **overrides)


def test_protocol_frame_sizes_are_fixed():
    protocol = load_protocol()
    assert protocol.CONTROL_FRAME_SIZE == 56
    assert protocol.ACK_FRAME_SIZE == 56


@pytest.mark.parametrize(
    "flag",
    [
        "EMERGENCY_STOP",
        "RESET_ESTOP",
        "STAND",
        "LIE",
    ],
)
def test_discrete_commands_round_trip_without_changing_frame_size(flag):
    protocol = load_protocol()
    command = getattr(protocol.ControlFlags, flag)
    frame = protocol.ControlFrame(
        session_id=1,
        sequence=2,
        arm_token=0,
        flags=command,
        vx=0.0,
        vy=0.0,
        vyaw=0.0,
    )

    assert len(protocol.encode_control(frame)) == 56
    assert protocol.decode_control(protocol.encode_control(frame)) == frame


def test_discrete_commands_reject_motion_and_flag_combinations():
    protocol = load_protocol()

    with pytest.raises(protocol.ProtocolError):
        protocol.ControlFrame(
            session_id=1,
            sequence=2,
            arm_token=0,
            flags=protocol.ControlFlags.STAND,
            vx=0.1,
            vy=0.0,
            vyaw=0.0,
        )
    with pytest.raises(protocol.ProtocolError):
        protocol.ControlFrame(
            session_id=1,
            sequence=2,
            arm_token=0,
            flags=(
                protocol.ControlFlags.STAND
                | protocol.ControlFlags.EMERGENCY_STOP
            ),
            vx=0.0,
            vy=0.0,
            vyaw=0.0,
        )


def test_control_matches_cross_language_golden_vector():
    protocol = load_protocol()
    payload = protocol.encode_control(valid_control(protocol))

    assert payload.hex() == CONTROL_GOLDEN_HEX
    assert protocol.decode_control(payload) == valid_control(protocol)


def test_ack_matches_cross_language_golden_vector():
    protocol = load_protocol()
    payload = protocol.encode_ack(valid_ack(protocol))

    assert payload.hex() == ACK_GOLDEN_HEX
    assert protocol.decode_ack(payload) == valid_ack(protocol)


@pytest.mark.parametrize("decoder_name,payload", [
    ("decode_control", bytes.fromhex(CONTROL_GOLDEN_HEX)),
    ("decode_ack", bytes.fromhex(ACK_GOLDEN_HEX)),
])
def test_crc_corruption_is_rejected(decoder_name, payload):
    protocol = load_protocol()
    corrupted = bytearray(payload)
    corrupted[20] ^= 0x01

    with pytest.raises(protocol.ProtocolError, match="CRC"):
        getattr(protocol, decoder_name)(bytes(corrupted))


@pytest.mark.parametrize("index,value,match", [
    (0, 0x00, "magic"),
    (5, 0x02, "version"),
    (7, 0x02, "type"),
    (9, 0x39, "length"),
])
def test_control_header_validation(index, value, match):
    protocol = load_protocol()
    payload = bytearray(bytes.fromhex(CONTROL_GOLDEN_HEX))
    payload[index] = value

    with pytest.raises(protocol.ProtocolError, match=match):
        protocol.decode_control(bytes(payload), verify_crc=False)


def test_wrong_buffer_length_is_rejected_before_unpacking():
    protocol = load_protocol()
    with pytest.raises(protocol.ProtocolError, match="length"):
        protocol.decode_control(b"\x00" * 12)


@pytest.mark.parametrize("field", ["vx", "vy", "vyaw"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_control_velocity_is_rejected(field, value):
    protocol = load_protocol()
    with pytest.raises(protocol.ProtocolError, match="finite"):
        protocol.encode_control(valid_control(protocol, **{field: value}))


def test_conflicting_arm_and_disarm_flags_are_rejected():
    protocol = load_protocol()
    flags = protocol.ControlFlags.ARM_REQUEST | protocol.ControlFlags.DISARM

    with pytest.raises(protocol.ProtocolError, match="flags"):
        protocol.encode_control(valid_control(protocol, flags=flags))


def test_unknown_gateway_state_is_rejected():
    protocol = load_protocol()
    payload = bytearray(bytes.fromhex(ACK_GOLDEN_HEX))
    payload[39] = 99

    with pytest.raises(protocol.ProtocolError, match="state"):
        protocol.decode_ack(bytes(payload), verify_crc=False)
