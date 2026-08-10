"""Safety policy for the guarded, short Go2 motion smoke test."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable, Mapping, Protocol


ACTIVE_NAV_STATES = frozenset({"ACCEPTED", "EXECUTING", "CANCELING"})


class SmokeTestAbort(RuntimeError):
    """Raised when a preflight or runtime safety condition is not satisfied."""


class SmokeTestIo(Protocol):
    def get_state(self) -> Mapping[str, object]: ...

    def manual_command(self, vx: float, vy: float, vyaw: float) -> None: ...


@dataclass(frozen=True)
class SmokeTestConfig:
    confirm_safe: bool = False
    vx: float = 0.2
    duration_sec: float = 2.0
    command_hz: float = 20.0
    min_abs_vx: float = 0.2
    max_abs_vx: float = 0.2
    max_duration_sec: float = 2.0
    ack_timeout_sec: float = 0.4
    stop_repeat_count: int = 3

    def validate(self) -> None:
        if not self.confirm_safe:
            raise ValueError(
                "--confirm-safe is required after checking the robot surroundings"
            )
        finite_values = (
            self.vx,
            self.duration_sec,
            self.command_hz,
            self.min_abs_vx,
            self.max_abs_vx,
            self.max_duration_sec,
            self.ack_timeout_sec,
        )
        if not all(math.isfinite(float(value)) for value in finite_values):
            raise ValueError("smoke-test limits must be finite")
        if self.min_abs_vx <= 0.0 or self.min_abs_vx > self.max_abs_vx:
            raise ValueError("smoke-test speed envelope is invalid")
        if abs(self.vx) < self.min_abs_vx:
            raise ValueError(
                f"|vx| must be >= {self.min_abs_vx:.3f} m/s "
                "to enter the verified Go2 walking gait"
            )
        if abs(self.vx) > self.max_abs_vx:
            raise ValueError(
                f"|vx| must be <= {self.max_abs_vx:.3f} m/s"
            )
        if self.duration_sec <= 0.0 or self.duration_sec > self.max_duration_sec:
            raise ValueError(
                f"duration must be in (0, {self.max_duration_sec:.3f}] seconds"
            )
        if self.command_hz <= 0.0:
            raise ValueError("command_hz must be positive")
        if self.ack_timeout_sec <= 0.0:
            raise ValueError("ack_timeout_sec must be positive")
        if self.stop_repeat_count < 1:
            raise ValueError("stop_repeat_count must be at least one")


def _validate_status(
    status: Mapping[str, object],
    *,
    ack_timeout_sec: float,
) -> None:
    if str(status.get("gateway_link", "offline")).lower() != "online":
        raise SmokeTestAbort("gateway is offline")

    ack_age = status.get("last_ack_age_sec")
    if (
        ack_age is None
        or not math.isfinite(float(ack_age))
        or float(ack_age) > ack_timeout_sec
    ):
        raise SmokeTestAbort(
            f"ACK is missing or older than {ack_timeout_sec:.3f}s"
        )

    nav_state = str(status.get("nav2_status", "UNKNOWN")).upper()
    if nav_state in ACTIVE_NAV_STATES:
        raise SmokeTestAbort(f"Nav2 is active ({nav_state})")

def run_smoke_test(
    io: SmokeTestIo,
    config: SmokeTestConfig,
    *,
    clock: Callable[[], float] = time.monotonic,
    waiter: Callable[[float], None] = time.sleep,
) -> None:
    """Run one bounded motion pulse and always finish with repeated zero."""

    config.validate()
    _validate_status(
        io.get_state(),
        ack_timeout_sec=config.ack_timeout_sec,
    )

    try:
        started_at = clock()
        period = 1.0 / config.command_hz
        while clock() - started_at < config.duration_sec:
            _validate_status(
                io.get_state(),
                ack_timeout_sec=config.ack_timeout_sec,
            )
            io.manual_command(config.vx, 0.0, 0.0)
            waiter(period)
    finally:
        for _ in range(config.stop_repeat_count):
            io.manual_command(0.0, 0.0, 0.0)
