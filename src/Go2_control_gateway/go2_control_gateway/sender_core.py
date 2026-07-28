"""Fail-closed state machine for the external UDP command sender.

This module deliberately contains no ROS or socket code.  Keeping time, command
selection, arming, and ACK handling in a deterministic core makes the safety
rules independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import secrets
import time
from typing import Callable, Optional, Tuple

from .protocol import AckFrame, ControlFlags, ControlFrame, FaultReason, GatewayState


Velocity = Tuple[float, float, float]


@dataclass(frozen=True)
class SenderConfig:
    max_vx: float = 0.6
    max_vy: float = 0.0
    max_vyaw: float = 1.4
    velocity_deadband: float = 0.03
    vyaw_smooth_alpha: float = 0.35
    nav_cmd_timeout_sec: float = 0.6
    manual_cmd_timeout_sec: float = 0.2
    ack_timeout_sec: float = 0.5
    arm_timeout_sec: float = 1.0
    localization_guard_enabled: bool = True
    localization_timeout_sec: float = 1.5
    correction_pause_sec: float = 0.8
    correction_pause_delta_xy: float = 0.5
    correction_pause_delta_yaw: float = 0.7

    def __post_init__(self) -> None:
        nonnegative = (
            "max_vx",
            "max_vy",
            "max_vyaw",
            "velocity_deadband",
            "nav_cmd_timeout_sec",
            "manual_cmd_timeout_sec",
            "ack_timeout_sec",
            "arm_timeout_sec",
            "localization_timeout_sec",
            "correction_pause_sec",
            "correction_pause_delta_xy",
            "correction_pause_delta_yaw",
        )
        for name in nonnegative:
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if not math.isfinite(self.vyaw_smooth_alpha):
            raise ValueError("vyaw_smooth_alpha must be finite")
        if not 0.0 < self.vyaw_smooth_alpha <= 1.0:
            raise ValueError("vyaw_smooth_alpha must be in (0, 1]")


class SenderCore:
    """Owns sender safety state and produces one control frame per tick."""

    def __init__(
        self,
        *,
        config: Optional[SenderConfig] = None,
        clock: Callable[[], float] = time.monotonic,
        token_source: Callable[[], int] = lambda: secrets.randbits(64),
        session_id: Optional[int] = None,
    ) -> None:
        self.config = config or SenderConfig()
        self._clock = clock
        self._token_source = token_source
        self._session_id = (
            int(session_id) if session_id is not None else self._new_nonzero_id()
        )
        if self._session_id <= 0 or self._session_id > 0xFFFFFFFFFFFFFFFF:
            raise ValueError("session_id must be a nonzero uint64")

        self._sequence = 0
        self._last_sent_sequence = 0
        self._last_ack_sequence = 0
        self._arm_token = 0
        self._revoked_tokens: set[int] = set()
        self._arm_requested_at: Optional[float] = None
        self._last_ack_at: Optional[float] = None
        self._armed = False
        self._disarm_pending = False

        self._nav_active = False
        self._nav_velocity: Velocity = (0.0, 0.0, 0.0)
        self._manual_velocity: Velocity = (0.0, 0.0, 0.0)
        self._nav_cmd_at: Optional[float] = None
        self._manual_cmd_at: Optional[float] = None
        self._last_filtered_yaw = 0.0

        self._localization: Optional[Velocity] = None
        self._localization_at: Optional[float] = None
        self._motion_paused_until = 0.0

    @property
    def is_armed(self) -> bool:
        return self._armed

    @property
    def arm_token(self) -> int:
        return self._arm_token

    @property
    def revoked_tokens(self) -> frozenset[int]:
        return frozenset(self._revoked_tokens)

    @property
    def nav_active(self) -> bool:
        return self._nav_active

    def _new_nonzero_id(self) -> int:
        for _ in range(1024):
            candidate = int(self._token_source())
            if 0 < candidate <= 0xFFFFFFFFFFFFFFFF:
                return candidate
        raise RuntimeError("token source did not produce a nonzero uint64")

    def _new_arm_token(self) -> int:
        for _ in range(1024):
            candidate = int(self._token_source())
            if (
                0 < candidate <= 0xFFFFFFFFFFFFFFFF
                and candidate != self._arm_token
                and candidate not in self._revoked_tokens
            ):
                return candidate
        raise RuntimeError("token source did not produce a fresh arm token")

    def request_arm(self) -> int:
        if self._armed or self._arm_requested_at is not None:
            return self._arm_token
        self._disarm_pending = False
        self._arm_token = self._new_arm_token()
        self._arm_requested_at = self._clock()
        self._last_ack_at = None
        return self._arm_token

    def request_disarm(self) -> None:
        if self._arm_token == 0:
            self._armed = False
            self._arm_requested_at = None
            self._disarm_pending = False
            self._clear_commands()
            return
        self._armed = False
        self._arm_requested_at = None
        self._disarm_pending = True
        self._clear_commands()

    def abort_arm(self) -> None:
        """Revoke the current token after an Arm attempt cannot be confirmed."""
        self._fail_closed()

    def set_nav_active(self, active: bool) -> None:
        active = bool(active)
        if active == self._nav_active:
            return
        self._nav_active = active
        self._clear_commands()

    def update_nav_cmd(self, vx: float, vy: float, vyaw: float) -> bool:
        value = self._sanitize_velocity(vx, vy, vyaw)
        now = self._clock()
        if value is None:
            self._nav_velocity = (0.0, 0.0, 0.0)
            self._nav_cmd_at = now
            return False
        self._nav_velocity = value
        self._nav_cmd_at = now
        return True

    def update_manual_cmd(self, vx: float, vy: float, vyaw: float) -> bool:
        if self._nav_active:
            return False
        value = self._sanitize_velocity(vx, vy, vyaw)
        now = self._clock()
        if value is None:
            self._manual_velocity = (0.0, 0.0, 0.0)
            self._manual_cmd_at = now
            return False
        self._manual_velocity = value
        self._manual_cmd_at = now
        return True

    def update_localization(self, x: float, y: float, yaw: float) -> bool:
        values = (float(x), float(y), float(yaw))
        if not all(math.isfinite(value) for value in values):
            return False
        now = self._clock()
        normalized = (values[0], values[1], self._normalize_angle(values[2]))
        if self._localization is not None:
            dx = normalized[0] - self._localization[0]
            dy = normalized[1] - self._localization[1]
            dyaw = self._normalize_angle(normalized[2] - self._localization[2])
            if (
                math.hypot(dx, dy) > self.config.correction_pause_delta_xy
                or abs(dyaw) > self.config.correction_pause_delta_yaw
            ):
                self._motion_paused_until = max(
                    self._motion_paused_until,
                    now + self.config.correction_pause_sec,
                )
        self._localization = normalized
        self._localization_at = now
        return True

    def handle_ack(self, ack: AckFrame) -> bool:
        if ack.session_id != self._session_id:
            return False
        if ack.sequence <= self._last_ack_sequence:
            return False
        if ack.sequence > self._last_sent_sequence:
            return False
        if self._arm_token == 0:
            if ack.arm_token != 0 or ack.state != GatewayState.LOCKED:
                return False
            self._last_ack_sequence = ack.sequence
            self._last_ack_at = self._clock()
            return True
        if ack.arm_token != self._arm_token:
            return False

        self._last_ack_sequence = ack.sequence
        self._last_ack_at = self._clock()

        if ack.sdk_code != 0 or ack.fault != FaultReason.NONE:
            self._fail_closed()
            return True

        if self._disarm_pending:
            if ack.state == GatewayState.LOCKED:
                self._complete_disarm()
            return True

        if self._arm_requested_at is not None:
            if ack.state == GatewayState.ARMED:
                self._armed = True
                self._arm_requested_at = None
            elif ack.state not in (GatewayState.ARMING, GatewayState.LOCKED):
                self._fail_closed()
            return True

        if self._armed and ack.state != GatewayState.ARMED:
            self._fail_closed()
        return True

    def next_packet(self) -> ControlFrame:
        now = self._clock()
        self._apply_timeouts(now)
        self._sequence += 1
        self._last_sent_sequence = self._sequence

        flags = ControlFlags.NONE
        velocity = (0.0, 0.0, 0.0)
        if self._disarm_pending:
            flags = ControlFlags.DISARM
        elif self._arm_requested_at is not None:
            flags = ControlFlags.ARM_REQUEST
        elif self._armed:
            velocity = self._selected_velocity(now)

        # Re-apply hard limits immediately before serialization.  The internal
        # gateway applies the same limits independently.
        velocity = self._hard_limit(*velocity)
        return ControlFrame(
            session_id=self._session_id,
            sequence=self._sequence,
            arm_token=self._arm_token,
            flags=flags,
            vx=velocity[0],
            vy=velocity[1],
            vyaw=velocity[2],
        )

    def _apply_timeouts(self, now: float) -> None:
        if (
            self._arm_requested_at is not None
            and now - self._arm_requested_at > self.config.arm_timeout_sec
        ):
            self._fail_closed()
            return
        if (
            (self._armed or self._disarm_pending)
            and self._last_ack_at is not None
            and now - self._last_ack_at > self.config.ack_timeout_sec
        ):
            self._fail_closed()

    def _selected_velocity(self, now: float) -> Velocity:
        if not self._localization_allows_motion(now):
            return (0.0, 0.0, 0.0)
        if self._nav_active:
            if (
                self._nav_cmd_at is None
                or now - self._nav_cmd_at > self.config.nav_cmd_timeout_sec
            ):
                return (0.0, 0.0, 0.0)
            return self._nav_velocity
        if (
            self._manual_cmd_at is None
            or now - self._manual_cmd_at > self.config.manual_cmd_timeout_sec
        ):
            return (0.0, 0.0, 0.0)
        return self._manual_velocity

    def _localization_allows_motion(self, now: float) -> bool:
        if not self.config.localization_guard_enabled:
            return True
        if self._localization_at is None:
            return False
        if now - self._localization_at > self.config.localization_timeout_sec:
            return False
        return now >= self._motion_paused_until

    def _sanitize_velocity(
        self, vx: float, vy: float, vyaw: float
    ) -> Optional[Velocity]:
        values = (float(vx), float(vy), float(vyaw))
        if not all(math.isfinite(value) for value in values):
            return None
        limited = self._hard_limit(*values)
        alpha = self.config.vyaw_smooth_alpha
        filtered_yaw = alpha * limited[2] + (1.0 - alpha) * self._last_filtered_yaw
        self._last_filtered_yaw = filtered_yaw
        return self._hard_limit(limited[0], limited[1], filtered_yaw)

    def _hard_limit(self, vx: float, vy: float, vyaw: float) -> Velocity:
        limited = (
            max(-self.config.max_vx, min(self.config.max_vx, float(vx))),
            max(-self.config.max_vy, min(self.config.max_vy, float(vy))),
            max(-self.config.max_vyaw, min(self.config.max_vyaw, float(vyaw))),
        )
        return tuple(
            0.0 if abs(value) < self.config.velocity_deadband else value
            for value in limited
        )

    def _clear_commands(self) -> None:
        self._nav_velocity = (0.0, 0.0, 0.0)
        self._manual_velocity = (0.0, 0.0, 0.0)
        self._nav_cmd_at = None
        self._manual_cmd_at = None
        self._last_filtered_yaw = 0.0

    def _fail_closed(self) -> None:
        if self._arm_token:
            self._revoked_tokens.add(self._arm_token)
        self._armed = False
        self._arm_token = 0
        self._arm_requested_at = None
        self._last_ack_at = None
        self._disarm_pending = False
        self._clear_commands()

    def _complete_disarm(self) -> None:
        if self._arm_token:
            self._revoked_tokens.add(self._arm_token)
        self._arm_token = 0
        self._armed = False
        self._arm_requested_at = None
        self._last_ack_at = None
        self._disarm_pending = False
        self._clear_commands()

    @staticmethod
    def _normalize_angle(value: float) -> float:
        return math.atan2(math.sin(value), math.cos(value))
