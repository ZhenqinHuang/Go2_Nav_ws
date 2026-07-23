#!/usr/bin/env python3
"""Validate the Go2 onboard Unitree L2 inputs without publishing commands."""

from collections import Counter
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
