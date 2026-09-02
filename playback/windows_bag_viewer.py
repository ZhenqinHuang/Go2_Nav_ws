#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
from rosbags.rosbag2 import Reader
from rosbags.typesys import Stores, get_typestore


TOPICS = (
    "/record/cloud_registered",
    "/fastlio_path",
    "/camera/color/image_raw",
    "/camera/depth/image_rect_raw",
)


def validate_topics(available: set[str]) -> None:
    missing = [topic for topic in TOPICS if topic not in available]
    if missing:
        raise ValueError(f"bag is missing required topics: {', '.join(missing)}")


def axis_bounds(cloud: np.ndarray, path: np.ndarray) -> tuple[np.ndarray, float]:
    nonempty = [points for points in (cloud, path) if points.size]
    if not nonempty:
        return np.zeros(3), 1.0
    points = np.vstack(nonempty)
    minimum = points.min(axis=0)
    maximum = points.max(axis=0)
    return (minimum + maximum) / 2, max(float((maximum - minimum).max() / 2), 1.0)


def combine_cloud_frames(frames: list[np.ndarray]) -> np.ndarray:
    nonempty = [frame for frame in frames if frame.size]
    return np.vstack(nonempty) if nonempty else np.empty((0, 3))


def height_colors(points: np.ndarray, brightness: float = 1.0) -> np.ndarray:
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points must have shape (n, 3)")
    if not 0.0 <= brightness <= 1.0:
        raise ValueError("brightness must be between 0 and 1")
    if not len(points):
        return np.empty((0, 3), dtype=np.uint8)
    heights = points[:, 2]
    span = np.ptp(heights)
    levels = (heights - heights.min()) / span if span else np.zeros(len(points))
    low = np.asarray([0.0, 76.0, 40.0])
    high = np.asarray([255.0, 180.0, 36.0])
    return np.rint((low + (high - low) * levels[:, None]) * brightness).astype(
        np.uint8
    )


def incremental_entity_path(frame_index: int) -> str:
    if frame_index < 0:
        raise ValueError("frame index must not be negative")
    return f"/incremental/map/frame_{frame_index:06d}"


def pointcloud_xyz(message) -> np.ndarray:
    offsets = {field.name: field.offset for field in message.fields}
    if not all(name in offsets for name in ("x", "y", "z")):
        raise ValueError("PointCloud2 does not contain x/y/z fields")
    byte_order = ">" if message.is_bigendian else "<"
    dtype = np.dtype(
        {
            "names": ["x", "y", "z"],
            "formats": [f"{byte_order}f4"] * 3,
            "offsets": [offsets["x"], offsets["y"], offsets["z"]],
            "itemsize": message.point_step,
        }
    )
    points = np.frombuffer(message.data, dtype=dtype, count=message.width * message.height)
    xyz = np.column_stack((points["x"], points["y"], points["z"]))
    return xyz[np.isfinite(xyz).all(axis=1)]


def image_array(message) -> np.ndarray:
    if message.encoding == "rgb8":
        row = np.frombuffer(message.data, dtype=np.uint8).reshape(message.height, message.step)
        return row[:, : message.width * 3].reshape(message.height, message.width, 3)
    if message.encoding == "16UC1":
        row = np.frombuffer(message.data, dtype="<u2").reshape(
            message.height, message.step // 2
        )
        return row[:, : message.width]
    raise ValueError(f"unsupported image encoding: {message.encoding}")


def path_xyz(message) -> np.ndarray:
    return np.asarray(
        [
            [pose.pose.position.x, pose.pose.position.y, pose.pose.position.z]
            for pose in message.poses
        ],
        dtype=float,
    ).reshape(-1, 3)


def check_bag(directory: Path) -> None:
    if not directory.is_dir():
        raise FileNotFoundError(f"bag directory not found: {directory}")
    with Reader(directory) as reader:
        validate_topics({connection.topic for connection in reader.connections})
        print(f"duration_seconds={(reader.end_time - reader.start_time) / 1e9:.3f}")
        for topic in TOPICS:
            connection = next(item for item in reader.connections if item.topic == topic)
            print(f"{topic}={connection.msgcount}")


def load_base_map(directory: Path, typestore) -> np.ndarray:
    frames = []
    with Reader(directory) as reader:
        connection = next(
            item
            for item in reader.connections
            if item.topic == "/record/cloud_registered"
        )
        for _, _, raw in reader.messages(connections=[connection]):
            frames.append(pointcloud_xyz(typestore.deserialize_cdr(raw, connection.msgtype)))
    return combine_cloud_frames(frames)


def play_bag(directory: Path) -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    if not directory.is_dir():
        raise FileNotFoundError(f"bag directory not found: {directory}")

    typestore = get_typestore(Stores.ROS2_FOXY)
    base_map = load_base_map(directory, typestore)
    reader = Reader(directory)
    reader.open()
    validate_topics({connection.topic for connection in reader.connections})
    connections = [item for item in reader.connections if item.topic in TOPICS]
    messages = iter(reader.messages(connections=connections))
    duration = (reader.end_time - reader.start_time) / 1e9

    root = tk.Tk()
    root.title("Leakage ROS2 Bag Viewer")
    root.geometry("1400x850")

    figure = Figure(figsize=(14, 8), tight_layout=True)
    figure.patch.set_facecolor("#101318")
    grid = figure.add_gridspec(2, 2, width_ratios=(1.4, 1.0))
    scene = figure.add_subplot(grid[:, 0], projection="3d")
    rgb_axis = figure.add_subplot(grid[0, 1])
    depth_axis = figure.add_subplot(grid[1, 1])
    scene.set_facecolor("#101318")
    scene.set_axis_off()
    rgb_axis.set_title("RGB")
    depth_axis.set_title("Depth")
    rgb_axis.axis("off")
    depth_axis.axis("off")

    scene.scatter(
        base_map[:, 0],
        base_map[:, 1],
        base_map[:, 2],
        s=0.5,
        color="#9aa0a6",
        alpha=0.18,
        depthshade=False,
    )
    cloud_artist = scene.scatter(
        [], [], [], s=8, color="#ffd23f", alpha=1.0, depthshade=False
    )
    (path_artist,) = scene.plot([], [], [], color="#00ff66", linewidth=2.5)
    center, radius = axis_bounds(base_map, np.empty((0, 3)))
    scene.set_xlim(center[0] - radius, center[0] + radius)
    scene.set_ylim(center[1] - radius, center[1] + radius)
    scene.set_zlim(center[2] - radius, center[2] + radius)
    scene.set_box_aspect((1, 1, 1))
    rgb_artist = rgb_axis.imshow(np.zeros((480, 640, 3), dtype=np.uint8))
    depth_artist = depth_axis.imshow(
        np.zeros((480, 640), dtype=np.uint16), cmap="turbo", vmin=0, vmax=4000
    )

    canvas = FigureCanvasTkAgg(figure, master=root)
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    controls = ttk.Frame(root, padding=6)
    controls.pack(fill=tk.X)
    elapsed_text = tk.StringVar(value=f"0.0 / {duration:.1f} s")
    progress = ttk.Progressbar(controls, maximum=duration)
    progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
    ttk.Label(controls, textvariable=elapsed_text, width=18).pack(side=tk.RIGHT)

    state = {
        "playing": True,
        "finished": False,
        "elapsed": 0.0,
        "last_wall": time.perf_counter(),
        "next": next(messages, None),
        "cloud": np.empty((0, 3)),
        "path": np.empty((0, 3)),
        "closed": False,
    }

    def toggle() -> None:
        if state["finished"]:
            return
        state["playing"] = not state["playing"]
        state["last_wall"] = time.perf_counter()
        toggle_button.configure(text="Pause" if state["playing"] else "Play")

    toggle_button = ttk.Button(controls, text="Pause", command=toggle)
    toggle_button.pack(side=tk.RIGHT, padx=(0, 10))

    def close() -> None:
        if not state["closed"]:
            reader.close()
            state["closed"] = True
        root.destroy()

    def redraw(changed: set[str]) -> None:
        if "/record/cloud_registered" in changed:
            cloud = state["cloud"]
            cloud_artist._offsets3d = (cloud[:, 0], cloud[:, 1], cloud[:, 2])
        if "/fastlio_path" in changed:
            path = state["path"]
            path_artist.set_data(path[:, 0], path[:, 1])
            path_artist.set_3d_properties(path[:, 2])
        if "/camera/color/image_raw" in changed:
            rgb_artist.set_data(state["rgb"])
        if "/camera/depth/image_rect_raw" in changed:
            depth = state["depth"]
            depth_artist.set_data(depth)
            valid = depth[depth > 0]
            depth_artist.set_clim(0, max(float(np.percentile(valid, 95)), 1.0))
        canvas.draw_idle()

    def tick() -> None:
        try:
            now = time.perf_counter()
            if state["playing"]:
                state["elapsed"] = min(
                    duration, state["elapsed"] + now - state["last_wall"]
                )
                target = reader.start_time + int(state["elapsed"] * 1e9)
                changed = set()
                while state["next"] is not None and state["next"][1] <= target:
                    connection, _, raw = state["next"]
                    message = typestore.deserialize_cdr(raw, connection.msgtype)
                    if connection.topic == "/record/cloud_registered":
                        state["cloud"] = pointcloud_xyz(message)
                    elif connection.topic == "/fastlio_path":
                        state["path"] = path_xyz(message)
                    elif connection.topic == "/camera/color/image_raw":
                        state["rgb"] = image_array(message)
                    elif connection.topic == "/camera/depth/image_rect_raw":
                        state["depth"] = image_array(message)
                    changed.add(connection.topic)
                    state["next"] = next(messages, None)
                if changed:
                    redraw(changed)
                if state["next"] is None:
                    state["playing"] = False
                    state["finished"] = True
                    toggle_button.configure(text="Finished", state=tk.DISABLED)
            state["last_wall"] = now
            progress["value"] = state["elapsed"]
            elapsed_text.set(f"{state['elapsed']:.1f} / {duration:.1f} s")
            root.after(33, tick)
        except Exception as error:
            messagebox.showerror("Playback error", str(error))
            close()

    root.protocol("WM_DELETE_WINDOW", close)
    root.after(0, tick)
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Display a synchronized leakage ROS2 bag")
    parser.add_argument("bag", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    directory = args.bag.resolve()
    if args.check:
        check_bag(directory)
    else:
        play_bag(directory)


if __name__ == "__main__":
    main()
