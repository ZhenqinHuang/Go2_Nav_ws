#!/usr/bin/env python3
"""One-shot, state-closed-loop Go2 forward-motion test.

The pure control helpers are importable without ROS so they can be unit tested
before this script is copied to the Jetson.
"""

from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ControlLimits:
    target_m: float
    stop_trigger_m: float
    max_motion_s: float
    max_state_age_s: float
    max_lateral_m: float
    max_reverse_m: float = 0.03
    max_distance_m: float = 0.45


def project_displacement(
    start_x: float,
    start_y: float,
    current_x: float,
    current_y: float,
    initial_yaw: float,
) -> Tuple[float, float, float]:
    dx = current_x - start_x
    dy = current_y - start_y
    cos_yaw = math.cos(initial_yaw)
    sin_yaw = math.sin(initial_yaw)
    forward = dx * cos_yaw + dy * sin_yaw
    lateral = -dx * sin_yaw + dy * cos_yaw
    return forward, lateral, math.hypot(dx, dy)


def evaluate_motion(
    *,
    forward_m: float,
    lateral_m: float,
    distance_m: float,
    elapsed_s: float,
    state_age_s: float,
    external_request_seen: bool,
    limits: ControlLimits,
) -> str:
    if external_request_seen:
        return "external_request"
    if state_age_s > limits.max_state_age_s:
        return "state_stale"
    if forward_m < -limits.max_reverse_m:
        return "reverse_limit"
    if abs(lateral_m) > limits.max_lateral_m:
        return "lateral_limit"
    if distance_m > limits.max_distance_m:
        return "distance_limit"
    if forward_m >= limits.stop_trigger_m:
        return "target_trigger"
    if elapsed_s >= limits.max_motion_s:
        return "hard_timeout"
    return "continue"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--armed", required=True, choices=["YES"])
    parser.add_argument("--speed", type=float, default=0.30)
    parser.add_argument("--target", type=float, default=0.40)
    parser.add_argument("--stop-trigger", type=float, default=0.38)
    parser.add_argument("--max-motion", type=float, default=1.80)
    parser.add_argument("--publish-rate", type=float, default=50.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (0.0 < args.speed <= 0.30):
        raise SystemExit("speed must be in (0, 0.30]")
    if not (0.0 < args.stop_trigger <= args.target <= 0.40):
        raise SystemExit("require 0 < stop-trigger <= target <= 0.40")
    if not (0.0 < args.max_motion <= 1.80):
        raise SystemExit("max-motion must be in (0, 1.80]")
    if not (20.0 <= args.publish_rate <= 50.0):
        raise SystemExit("publish-rate must be in [20, 50]")

    import rclpy
    from unitree_api.msg import Request, Response
    from unitree_go.msg import SportModeState

    limits = ControlLimits(
        target_m=args.target,
        stop_trigger_m=args.stop_trigger,
        max_motion_s=args.max_motion,
        max_state_age_s=0.15,
        max_lateral_m=0.15,
    )

    rclpy.init()
    node = rclpy.create_node("codex_go2_closed_loop_test")
    request_pub = node.create_publisher(Request, "/api/sport/request", 10)

    state: Optional[SportModeState] = None
    state_received_at = 0.0
    state_samples = 0
    own_request_ids = set()
    external_request_seen = False
    external_request_api = None
    response_codes = {}
    stop_signal = False

    def state_callback(msg: SportModeState) -> None:
        nonlocal state, state_received_at, state_samples
        state = msg
        state_received_at = time.monotonic()
        state_samples += 1

    def request_callback(msg: Request) -> None:
        nonlocal external_request_seen, external_request_api
        request_id = int(msg.header.identity.id)
        if request_id not in own_request_ids:
            external_request_seen = True
            external_request_api = int(msg.header.identity.api_id)

    def response_callback(msg: Response) -> None:
        response_codes[int(msg.header.identity.id)] = int(msg.header.status.code)

    node.create_subscription(SportModeState, "/lf/sportmodestate", state_callback, 10)
    node.create_subscription(Request, "/api/sport/request", request_callback, 10)
    node.create_subscription(Response, "/api/sport/response", response_callback, 10)

    def publish_request(api_id: int, parameter: str = "") -> int:
        request = Request()
        request_id = time.monotonic_ns()
        own_request_ids.add(request_id)
        request.header.identity.id = request_id
        request.header.identity.api_id = api_id
        request.header.lease.id = 0
        request.header.policy.priority = 0
        request.header.policy.noreply = False
        request.parameter = parameter
        request.binary = []
        request_pub.publish(request)
        return request_id

    def publish_move() -> int:
        parameter = json.dumps(
            {"x": args.speed, "y": 0.0, "z": 0.0},
            separators=(",", ":"),
        )
        return publish_request(1008, parameter)

    def publish_stop_burst() -> None:
        for _ in range(5):
            publish_request(1003)
            rclpy.spin_once(node, timeout_sec=0.02)
            time.sleep(0.03)

    def on_signal(_signum, _frame) -> None:
        nonlocal stop_signal
        stop_signal = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    decision = "not_started"
    start_x = start_y = start_yaw = 0.0
    forward = lateral = distance = 0.0
    elapsed = 0.0
    start_time = 0.0
    move_requests = 0

    try:
        # Observe state and request traffic before arming motion.
        preflight_deadline = time.monotonic() + 3.0
        while time.monotonic() < preflight_deadline and state_samples < 10:
            rclpy.spin_once(node, timeout_sec=0.05)

        if state is None or state_samples < 3:
            decision = "preflight_no_state"
            return_code = 2
        elif external_request_seen:
            decision = "preflight_external_request"
            return_code = 2
        elif math.hypot(float(state.velocity[0]), float(state.velocity[1])) > 0.05:
            decision = "preflight_robot_not_still"
            return_code = 2
        else:
            start_x = float(state.position[0])
            start_y = float(state.position[1])
            start_yaw = float(state.imu_state.rpy[2])
            print(
                "ARMED "
                f"start=({start_x:.4f},{start_y:.4f}) yaw={start_yaw:.4f} "
                f"mode={int(state.mode)} gait={int(state.gait_type)}",
                flush=True,
            )

            start_time = time.monotonic()
            next_publish = start_time
            next_log = start_time
            decision = "continue"

            while decision == "continue" and not stop_signal:
                rclpy.spin_once(node, timeout_sec=0.005)
                now = time.monotonic()

                if now >= next_publish:
                    publish_move()
                    move_requests += 1
                    next_publish += 1.0 / args.publish_rate

                if state is not None:
                    forward, lateral, distance = project_displacement(
                        start_x,
                        start_y,
                        float(state.position[0]),
                        float(state.position[1]),
                        start_yaw,
                    )
                elapsed = now - start_time
                state_age = now - state_received_at
                decision = evaluate_motion(
                    forward_m=forward,
                    lateral_m=lateral,
                    distance_m=distance,
                    elapsed_s=elapsed,
                    state_age_s=state_age,
                    external_request_seen=external_request_seen,
                    limits=limits,
                )

                if now >= next_log:
                    mode = int(state.mode) if state is not None else -1
                    gait = int(state.gait_type) if state is not None else -1
                    vx = float(state.velocity[0]) if state is not None else math.nan
                    print(
                        "SAMPLE "
                        f"t={elapsed:.3f} forward={forward:.4f} "
                        f"lateral={lateral:.4f} distance={distance:.4f} "
                        f"vx={vx:.4f} mode={mode} gait={gait} "
                        f"decision={decision}",
                        flush=True,
                    )
                    next_log += 0.10

            if stop_signal and decision == "continue":
                decision = "signal"
            return_code = 0 if decision == "target_trigger" else 3
    finally:
        # StopMove is always sent, including every preflight failure and signal.
        try:
            publish_stop_burst()
            settle_deadline = time.monotonic() + 0.8
            while time.monotonic() < settle_deadline:
                rclpy.spin_once(node, timeout_sec=0.02)
                if state is not None:
                    forward, lateral, distance = project_displacement(
                        start_x,
                        start_y,
                        float(state.position[0]),
                        float(state.position[1]),
                        start_yaw,
                    )
        finally:
            result = {
                "decision": decision,
                "elapsed_s": round(elapsed, 4),
                "forward_m": round(forward, 4),
                "lateral_m": round(lateral, 4),
                "distance_m": round(distance, 4),
                "move_requests": move_requests,
                "external_request_seen": external_request_seen,
                "external_request_api": external_request_api,
                "response_ok": sum(code == 0 for code in response_codes.values()),
                "mode": int(state.mode) if state is not None else None,
                "gait_type": int(state.gait_type) if state is not None else None,
                "velocity": (
                    [round(float(v), 4) for v in state.velocity]
                    if state is not None
                    else None
                ),
            }
            print("RESULT " + json.dumps(result, sort_keys=True), flush=True)
            node.destroy_node()
            rclpy.shutdown()

    return return_code


if __name__ == "__main__":
    sys.exit(main())
