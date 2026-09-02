from __future__ import annotations

from typing import Sequence, TypeVar


PoseType = TypeVar("PoseType")


def append_pose(
    poses: Sequence[PoseType], pose: PoseType, *, max_length: int
) -> list[PoseType]:
    if max_length < 1:
        raise ValueError("max_length must be positive")
    return [*poses, pose][-max_length:]


def should_publish_path(
    last_publish_seconds: float | None,
    now_seconds: float,
    *,
    interval_seconds: float,
) -> bool:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    return last_publish_seconds is None or now_seconds - last_publish_seconds >= interval_seconds
