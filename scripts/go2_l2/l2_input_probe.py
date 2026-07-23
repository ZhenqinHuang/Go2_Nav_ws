#!/usr/bin/env python3
"""Validate the Go2 onboard Unitree L2 inputs without publishing commands."""

import argparse
from collections import Counter
import json
from pathlib import Path
import struct
import time
from typing import Dict, Iterable, List, Mapping, Optional, Union


FLOAT32 = 7
UINT16 = 4
REQUIRED_FIELDS = {
    "x": FLOAT32,
    "y": FLOAT32,
    "z": FLOAT32,
    "intensity": FLOAT32,
    "ring": UINT16,
    "time": FLOAT32,
}

Number = Union[int, float]


def validate_point_fields(fields: Mapping[str, int]) -> List[str]:
    """Return PointCloud2 field contract errors in a deterministic order."""
    errors = []
    for name, expected_datatype in REQUIRED_FIELDS.items():
        if name not in fields:
            errors.append(f"missing PointCloud2 field: {name}")
            continue
        actual_datatype = fields[name]
        if actual_datatype != expected_datatype:
            errors.append(
                f"PointCloud2 field {name} has datatype "
                f"{actual_datatype}, expected {expected_datatype}"
            )
    return errors


def analyze_point_times(times: Iterable[Number]) -> Dict[str, object]:
    """Summarize per-point offsets and infer the raw laser sampling rate."""
    values = [float(value) for value in times]
    if not values:
        return {
            "count": 0,
            "min_s": None,
            "max_s": None,
            "span_s": None,
            "monotonic": False,
            "mode_positive_delta_s": None,
            "raw_sampling_hz": None,
            "errors": ["point time array is empty"],
        }

    deltas = [current - previous for previous, current in zip(values, values[1:])]
    monotonic = all(delta >= 0.0 for delta in deltas)
    positive_ns = [round(delta * 1e9) for delta in deltas if delta > 0.0]
    errors = []
    if not monotonic:
        errors.append("point time values regress")

    mode_delta_s: Optional[float] = None
    raw_sampling_hz: Optional[float] = None
    if positive_ns:
        mode_ns = Counter(positive_ns).most_common(1)[0][0]
        if mode_ns > 0:
            mode_delta_s = mode_ns / 1e9
            raw_sampling_hz = 1.0 / mode_delta_s
    else:
        errors.append("point time values have no positive interval")

    minimum = min(values)
    maximum = max(values)
    return {
        "count": len(values),
        "min_s": minimum,
        "max_s": maximum,
        "span_s": maximum - minimum,
        "monotonic": monotonic,
        "mode_positive_delta_s": mode_delta_s,
        "raw_sampling_hz": raw_sampling_hz,
        "errors": errors,
    }


def classify_unitree_lidar(
    raw_sampling_hz: Optional[Number],
    effective_points_hz: Optional[Number],
) -> str:
    """Classify L1/L2 from their documented raw and effective point rates."""
    if not raw_sampling_hz or not effective_points_hz:
        return "unknown"

    observed_raw = float(raw_sampling_hz)
    observed_effective = float(effective_points_hz)
    references = {
        "L1": (43200.0, 21600.0),
        "L2": (128000.0, 64000.0),
    }
    scores = {}
    for model, (reference_raw, reference_effective) in references.items():
        scores[model] = max(
            abs(observed_raw - reference_raw) / reference_raw,
            abs(observed_effective - reference_effective) / reference_effective,
        )

    model = min(scores, key=scores.get)
    return model if scores[model] <= 0.35 else "unknown"


def evaluate_rates(cloud_hz: Number, imu_hz: Number) -> List[str]:
    """Check the bounded rates needed by the first FAST-LIO2 smoke test."""
    errors = []
    cloud_rate = float(cloud_hz)
    imu_rate = float(imu_hz)
    if not 10.0 <= cloud_rate <= 30.0:
        errors.append(
            f"cloud rate {cloud_rate:.3f} Hz is outside 10.0-30.0 Hz"
        )
    if not 200.0 <= imu_rate <= 350.0:
        errors.append(
            f"IMU rate {imu_rate:.3f} Hz is outside 200.0-350.0 Hz"
        )
    return errors


def build_report(
    *,
    field_datatypes: Mapping[str, int],
    point_times: Iterable[Number],
    cloud_hz: Number,
    imu_hz: Number,
    effective_points_hz: Number,
    cloud_messages: int,
    imu_messages: int,
    ring_values: Iterable[int],
    timestamp_regressions: int,
    wall_clock_offset_s: Optional[Number],
) -> Dict[str, object]:
    """Build the bounded, machine-readable readiness report."""
    time_analysis = analyze_point_times(point_times)
    raw_sampling_hz = time_analysis["raw_sampling_hz"]
    detected_model = classify_unitree_lidar(
        raw_sampling_hz=raw_sampling_hz,
        effective_points_hz=effective_points_hz,
    )

    errors = []
    errors.extend(validate_point_fields(field_datatypes))
    errors.extend(time_analysis["errors"])
    errors.extend(evaluate_rates(cloud_hz, imu_hz))
    if cloud_messages < 2:
        errors.append(
            f"received {cloud_messages} cloud messages, expected at least 2"
        )
    if imu_messages < 2:
        errors.append(f"received {imu_messages} IMU messages, expected at least 2")
    if timestamp_regressions:
        errors.append(
            f"detected {timestamp_regressions} ROS timestamp regressions"
        )
    if wall_clock_offset_s is None:
        errors.append("unable to compare ROS and Jetson wall clocks")
    elif abs(float(wall_clock_offset_s)) > 2.0:
        errors.append(
            "latest sensor timestamp differs from Jetson wall clock by "
            f"{float(wall_clock_offset_s):.6f} s"
        )
    if detected_model != "L2":
        errors.append(
            f"detected lidar model {detected_model}, expected L2"
        )

    return {
        "schema_version": 1,
        "detected_model": detected_model,
        "ready_for_fastlio2": not errors,
        "errors": errors,
        "topics": {
            "cloud": "/utlidar/cloud",
            "imu": "/utlidar/imu",
        },
        "field_datatypes": dict(sorted(field_datatypes.items())),
        "ring_values": sorted({int(value) for value in ring_values}),
        "cloud_messages": int(cloud_messages),
        "imu_messages": int(imu_messages),
        "cloud_hz": float(cloud_hz),
        "imu_hz": float(imu_hz),
        "effective_points_hz": float(effective_points_hz),
        "point_time": time_analysis,
        "timestamp_regressions": int(timestamp_regressions),
        "wall_clock_offset_s": (
            None
            if wall_clock_offset_s is None
            else float(wall_clock_offset_s)
        ),
    }


def _stamp_seconds(message) -> float:
    return (
        float(message.header.stamp.sec)
        + float(message.header.stamp.nanosec) * 1e-9
    )


def _message_rate(stamps: List[float]) -> float:
    if len(stamps) < 2:
        return 0.0
    span = stamps[-1] - stamps[0]
    return (len(stamps) - 1) / span if span > 0.0 else 0.0


def _count_regressions(stamps: List[float]) -> int:
    return sum(
        current < previous
        for previous, current in zip(stamps, stamps[1:])
    )


def _run_live_probe(duration_s: float) -> Dict[str, object]:
    # ROS imports deliberately stay inside the live entry point. This keeps the
    # validation core importable on development machines without ROS 2.
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import (
        DurabilityPolicy,
        HistoryPolicy,
        QoSProfile,
        ReliabilityPolicy,
    )
    from sensor_msgs.msg import Imu, PointCloud2

    class L2InputProbe(Node):
        def __init__(self):
            super().__init__("go2_l2_input_probe")
            qos = QoSProfile(
                history=HistoryPolicy.KEEP_LAST,
                depth=20,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.VOLATILE,
            )
            self.cloud_stamps: List[float] = []
            self.cloud_points: List[int] = []
            self.imu_stamps: List[float] = []
            self.field_datatypes: Dict[str, int] = {}
            self.point_times: List[float] = []
            self.ring_values = set()
            self.decode_errors: List[str] = []
            self.cloud_subscription = self.create_subscription(
                PointCloud2,
                "/utlidar/cloud",
                self.on_cloud,
                qos,
            )
            self.imu_subscription = self.create_subscription(
                Imu,
                "/utlidar/imu",
                self.on_imu,
                qos,
            )

        def on_imu(self, message):
            self.imu_stamps.append(_stamp_seconds(message))

        def on_cloud(self, message):
            self.cloud_stamps.append(_stamp_seconds(message))
            self.cloud_points.append(int(message.width * message.height))
            if self.point_times or self.decode_errors:
                return

            fields = {field.name: field for field in message.fields}
            self.field_datatypes = {
                name: int(field.datatype) for name, field in fields.items()
            }
            field_errors = validate_point_fields(self.field_datatypes)
            if field_errors:
                self.decode_errors.extend(field_errors)
                return

            byte_order = ">" if message.is_bigendian else "<"
            time_field = fields["time"]
            ring_field = fields["ring"]
            try:
                for index in range(message.width * message.height):
                    point_offset = index * message.point_step
                    self.point_times.append(
                        struct.unpack_from(
                            f"{byte_order}f",
                            message.data,
                            point_offset + time_field.offset,
                        )[0]
                    )
                    self.ring_values.add(
                        struct.unpack_from(
                            f"{byte_order}H",
                            message.data,
                            point_offset + ring_field.offset,
                        )[0]
                    )
            except (struct.error, TypeError, ValueError) as error:
                self.decode_errors.append(
                    f"failed to decode PointCloud2 time/ring: {error}"
                )

    rclpy.init(args=None)
    node = L2InputProbe()
    try:
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
    finally:
        node.destroy_node()
        rclpy.shutdown()

    cloud_hz = _message_rate(node.cloud_stamps)
    imu_hz = _message_rate(node.imu_stamps)
    effective_points_hz = 0.0
    if len(node.cloud_stamps) >= 2:
        cloud_span = node.cloud_stamps[-1] - node.cloud_stamps[0]
        if cloud_span > 0.0:
            effective_points_hz = sum(node.cloud_points[1:]) / cloud_span

    all_stamps = node.cloud_stamps + node.imu_stamps
    wall_clock_offset_s = None
    if all_stamps:
        wall_clock_offset_s = time.time() - max(all_stamps)

    report = build_report(
        field_datatypes=node.field_datatypes,
        point_times=node.point_times,
        cloud_hz=cloud_hz,
        imu_hz=imu_hz,
        effective_points_hz=effective_points_hz,
        cloud_messages=len(node.cloud_stamps),
        imu_messages=len(node.imu_stamps),
        ring_values=node.ring_values,
        timestamp_regressions=(
            _count_regressions(node.cloud_stamps)
            + _count_regressions(node.imu_stamps)
        ),
        wall_clock_offset_s=wall_clock_offset_s,
    )
    if node.decode_errors:
        report["errors"] = node.decode_errors + report["errors"]
        report["ready_for_fastlio2"] = False
    return report


def _write_report(report: Mapping[str, object], report_path: Optional[str]) -> None:
    serialized = json.dumps(report, indent=2, sort_keys=True)
    print(serialized)
    if report_path:
        Path(report_path).write_text(serialized + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only validation of Go2 onboard L2 point cloud and IMU inputs"
        )
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=6.0,
        help="sampling duration in seconds (default: 6)",
    )
    parser.add_argument(
        "--report",
        help="optional JSON report output path",
    )
    args = parser.parse_args()
    if args.duration <= 0.0:
        parser.error("--duration must be positive")

    try:
        report = _run_live_probe(args.duration)
    except Exception as error:
        report = {
            "schema_version": 1,
            "detected_model": "unknown",
            "ready_for_fastlio2": False,
            "errors": [f"probe failed: {type(error).__name__}: {error}"],
        }
    _write_report(report, args.report)
    return 0 if report["ready_for_fastlio2"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
