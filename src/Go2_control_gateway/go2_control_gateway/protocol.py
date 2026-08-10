"""Versioned binary protocol shared by the external and internal gateways."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, IntFlag
import math
import struct
import zlib


MAGIC = 0x47324757  # ASCII: G2GW
VERSION = 1
PACKET_TYPE_CONTROL = 1
PACKET_TYPE_ACK = 2

_CONTROL_STRUCT = struct.Struct("!IHHHHQQQIfffI")
_ACK_STRUCT = struct.Struct("!IHHHHQQQIiIII")
CONTROL_FRAME_SIZE = _CONTROL_STRUCT.size
ACK_FRAME_SIZE = _ACK_STRUCT.size


class ProtocolError(ValueError):
    """Raised when a gateway packet violates the wire contract."""


class ControlFlags(IntFlag):
    NONE = 0
    ARM_REQUEST = 1 << 0
    DISARM = 1 << 1
    EMERGENCY_STOP = 1 << 2
    RESET_ESTOP = 1 << 3
    STAND = 1 << 4
    LIE = 1 << 5


class AckFlags(IntFlag):
    NONE = 0
    ESTOP_LATCHED = 1 << 0
    COMMAND_ACCEPTED = 1 << 1
    POSTURE_STANDING = 1 << 2
    POSTURE_LYING = 1 << 3


class GatewayState(IntEnum):
    LOCKED = 0
    ARMING = 1
    ARMED = 2
    FAULT = 3


class FaultReason(IntEnum):
    NONE = 0
    WATCHDOG = 1
    PROTOCOL = 2
    SDK = 3
    EXPLICIT_DISARM = 4
    SHUTDOWN = 5
    ESTOP = 6


def _as_float32(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ProtocolError("velocity fields must be finite")
    return struct.unpack("!f", struct.pack("!f", value))[0]


def _require_u64(name: str, value: int) -> int:
    value = int(value)
    if value < 0 or value > 0xFFFFFFFFFFFFFFFF:
        raise ProtocolError(f"{name} must fit uint64")
    return value


def _require_i32(name: str, value: int) -> int:
    value = int(value)
    if value < -0x80000000 or value > 0x7FFFFFFF:
        raise ProtocolError(f"{name} must fit int32")
    return value


def _validate_control_flags(value: ControlFlags | int) -> ControlFlags:
    raw = int(value)
    known = int(
        ControlFlags.ARM_REQUEST
        | ControlFlags.DISARM
        | ControlFlags.EMERGENCY_STOP
        | ControlFlags.RESET_ESTOP
        | ControlFlags.STAND
        | ControlFlags.LIE
    )
    if raw & ~known:
        raise ProtocolError("unknown control flags")
    if raw and raw & (raw - 1):
        raise ProtocolError("conflicting control flags")
    return ControlFlags(raw)


@dataclass(frozen=True)
class ControlFrame:
    session_id: int
    sequence: int
    arm_token: int
    flags: ControlFlags
    vx: float
    vy: float
    vyaw: float

    def __post_init__(self):
        object.__setattr__(self, "session_id", _require_u64("session_id", self.session_id))
        object.__setattr__(self, "sequence", _require_u64("sequence", self.sequence))
        object.__setattr__(self, "arm_token", _require_u64("arm_token", self.arm_token))
        object.__setattr__(self, "flags", _validate_control_flags(self.flags))
        object.__setattr__(self, "vx", _as_float32(self.vx))
        object.__setattr__(self, "vy", _as_float32(self.vy))
        object.__setattr__(self, "vyaw", _as_float32(self.vyaw))
        command_flags = (
            ControlFlags.EMERGENCY_STOP
            | ControlFlags.RESET_ESTOP
            | ControlFlags.STAND
            | ControlFlags.LIE
        )
        if self.flags & command_flags and any(
            value != 0.0 for value in (self.vx, self.vy, self.vyaw)
        ):
            raise ProtocolError("discrete commands require zero velocity")


@dataclass(frozen=True)
class AckFrame:
    session_id: int
    sequence: int
    arm_token: int
    state: GatewayState
    sdk_code: int
    fault: FaultReason
    flags: AckFlags | int = AckFlags.NONE

    def __post_init__(self):
        object.__setattr__(self, "session_id", _require_u64("session_id", self.session_id))
        object.__setattr__(self, "sequence", _require_u64("sequence", self.sequence))
        object.__setattr__(self, "arm_token", _require_u64("arm_token", self.arm_token))
        try:
            object.__setattr__(self, "state", GatewayState(int(self.state)))
        except ValueError as exc:
            raise ProtocolError("unknown gateway state") from exc
        object.__setattr__(self, "sdk_code", _require_i32("sdk_code", self.sdk_code))
        try:
            object.__setattr__(self, "fault", FaultReason(int(self.fault)))
        except ValueError as exc:
            raise ProtocolError("unknown fault reason") from exc
        raw_flags = int(self.flags)
        known_flags = int(
            AckFlags.ESTOP_LATCHED
            | AckFlags.COMMAND_ACCEPTED
            | AckFlags.POSTURE_STANDING
            | AckFlags.POSTURE_LYING
        )
        if raw_flags < 0 or raw_flags > 0xFFFFFFFF or raw_flags & ~known_flags:
            raise ProtocolError("unknown ACK flags")
        if (
            raw_flags & int(AckFlags.POSTURE_STANDING)
            and raw_flags & int(AckFlags.POSTURE_LYING)
        ):
            raise ProtocolError("conflicting posture flags")
        object.__setattr__(self, "flags", AckFlags(raw_flags))


def _append_crc(payload_without_crc: bytes) -> bytes:
    crc = zlib.crc32(payload_without_crc) & 0xFFFFFFFF
    return payload_without_crc + struct.pack("!I", crc)


def _check_buffer(payload: bytes, expected_size: int, verify_crc: bool) -> None:
    if len(payload) != expected_size:
        raise ProtocolError(
            f"packet length {len(payload)} does not match expected length {expected_size}"
        )
    if verify_crc:
        expected_crc = struct.unpack("!I", payload[-4:])[0]
        actual_crc = zlib.crc32(payload[:-4]) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ProtocolError(
                f"CRC mismatch: expected 0x{expected_crc:08x}, got 0x{actual_crc:08x}"
            )


def _check_header(
    magic: int,
    version: int,
    packet_type: int,
    declared_length: int,
    expected_type: int,
    expected_size: int,
) -> None:
    if magic != MAGIC:
        raise ProtocolError(f"invalid magic 0x{magic:08x}")
    if version != VERSION:
        raise ProtocolError(f"unsupported version {version}")
    if packet_type != expected_type:
        raise ProtocolError(f"unexpected packet type {packet_type}")
    if declared_length != expected_size:
        raise ProtocolError(
            f"declared length {declared_length} does not match {expected_size}"
        )


def encode_control(frame: ControlFrame) -> bytes:
    if not isinstance(frame, ControlFrame):
        raise ProtocolError("encode_control requires ControlFrame")
    body = struct.pack(
        "!IHHHHQQQIfff",
        MAGIC,
        VERSION,
        PACKET_TYPE_CONTROL,
        CONTROL_FRAME_SIZE,
        0,
        frame.session_id,
        frame.sequence,
        frame.arm_token,
        int(frame.flags),
        frame.vx,
        frame.vy,
        frame.vyaw,
    )
    return _append_crc(body)


def decode_control(payload: bytes, *, verify_crc: bool = True) -> ControlFrame:
    _check_buffer(payload, CONTROL_FRAME_SIZE, verify_crc)
    (
        magic,
        version,
        packet_type,
        declared_length,
        reserved,
        session_id,
        sequence,
        arm_token,
        flags,
        vx,
        vy,
        vyaw,
        _crc,
    ) = _CONTROL_STRUCT.unpack(payload)
    _check_header(
        magic,
        version,
        packet_type,
        declared_length,
        PACKET_TYPE_CONTROL,
        CONTROL_FRAME_SIZE,
    )
    if reserved != 0:
        raise ProtocolError("control reserved field must be zero")
    return ControlFrame(
        session_id=session_id,
        sequence=sequence,
        arm_token=arm_token,
        flags=ControlFlags(flags),
        vx=vx,
        vy=vy,
        vyaw=vyaw,
    )


def encode_ack(frame: AckFrame) -> bytes:
    if not isinstance(frame, AckFrame):
        raise ProtocolError("encode_ack requires AckFrame")
    body = struct.pack(
        "!IHHHHQQQIiII",
        MAGIC,
        VERSION,
        PACKET_TYPE_ACK,
        ACK_FRAME_SIZE,
        0,
        frame.session_id,
        frame.sequence,
        frame.arm_token,
        int(frame.state),
        frame.sdk_code,
        int(frame.fault),
        frame.flags,
    )
    return _append_crc(body)


def decode_ack(payload: bytes, *, verify_crc: bool = True) -> AckFrame:
    _check_buffer(payload, ACK_FRAME_SIZE, verify_crc)
    (
        magic,
        version,
        packet_type,
        declared_length,
        reserved,
        session_id,
        sequence,
        arm_token,
        state,
        sdk_code,
        fault,
        flags,
        _crc,
    ) = _ACK_STRUCT.unpack(payload)
    _check_header(
        magic,
        version,
        packet_type,
        declared_length,
        PACKET_TYPE_ACK,
        ACK_FRAME_SIZE,
    )
    if reserved != 0:
        raise ProtocolError("ACK reserved field must be zero")
    return AckFrame(
        session_id=session_id,
        sequence=sequence,
        arm_token=arm_token,
        state=state,
        sdk_code=sdk_code,
        fault=fault,
        flags=flags,
    )
