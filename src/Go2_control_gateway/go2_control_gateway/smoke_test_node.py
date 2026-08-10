"""Command-line entry point for one guarded Go2 motion pulse."""

from __future__ import annotations

import argparse
import math
import sys
import time
from typing import Callable, Mapping, Optional, Sequence

from .smoke_test_adapter import RclpySmokeTestAdapter
from .smoke_test_core import SmokeTestAbort, SmokeTestConfig, run_smoke_test


def wait_for_initial_status(
    adapter,
    *,
    timeout_sec: float = 5.0,
    clock: Callable[[], float] = time.monotonic,
    waiter: Callable[[float], None] = time.sleep,
) -> Mapping[str, object]:
    deadline = clock() + timeout_sec
    while True:
        state = adapter.get_state()
        ack_age = state.get("last_ack_age_sec")
        if (
            str(state.get("gateway_link", "offline")).lower() == "online"
            and ack_age is not None
            and math.isfinite(float(ack_age))
        ):
            return state
        remaining = deadline - clock()
        if remaining <= 0.0:
            raise SmokeTestAbort(
                "timed out waiting for the first gateway status sample"
            )
        waiter(min(0.05, remaining))


def parse_smoke_test_args(args: Optional[Sequence[str]] = None) -> SmokeTestConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Run one fail-closed Go2 motion pulse through the external-to-"
            "internal gateway."
        )
    )
    parser.add_argument(
        "--confirm-safe",
        action="store_true",
        help="confirm the robot is powered, supported, and its path is clear",
    )
    parser.add_argument(
        "--vx",
        type=float,
        default=0.2,
        help="forward velocity in m/s; verified smoke-test value is +/-0.2",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=2.0,
        help="motion duration in seconds; defaults to the 2.0 s hard limit",
    )
    parsed, _ros_args = parser.parse_known_args(args)
    return SmokeTestConfig(
        confirm_safe=parsed.confirm_safe,
        vx=parsed.vx,
        duration_sec=parsed.duration,
    )


def main(args: Optional[Sequence[str]] = None) -> None:
    config = parse_smoke_test_args(args)
    adapter = RclpySmokeTestAdapter()
    try:
        wait_for_initial_status(adapter)
        print(
            "Safety preflight: gateway online, Nav2 idle, ACK <= 0.4 s."
        )
        run_smoke_test(adapter, config)
        print("Smoke test completed; repeated zero velocity sent.")
    except (ValueError, SmokeTestAbort) as exc:
        print(f"Smoke test aborted: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    finally:
        adapter.close()


if __name__ == "__main__":
    main()
