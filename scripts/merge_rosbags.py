#!/usr/bin/env python3
import argparse
import json
import shutil
import sqlite3
from pathlib import Path


def bag_db(directory: Path) -> Path:
    files = list(directory.glob("*.db3"))
    if len(files) != 1:
        raise ValueError(f"expected one .db3 file in {directory}, found {len(files)}")
    return files[0]


def write_metadata(database: Path) -> None:
    connection = sqlite3.connect(database)
    try:
        message_count, start, end = connection.execute(
            "SELECT count(*), min(timestamp), max(timestamp) FROM messages"
        ).fetchone()
        if not message_count:
            raise ValueError("merged bag contains no messages")
        topics = connection.execute(
            "SELECT t.name, t.type, t.serialization_format, t.offered_qos_profiles, "
            "count(m.id) FROM topics t LEFT JOIN messages m ON m.topic_id = t.id "
            "GROUP BY t.id ORDER BY t.id"
        ).fetchall()
    finally:
        connection.close()

    lines = [
        "rosbag2_bagfile_information:",
        "  version: 4",
        "  storage_identifier: sqlite3",
        "  relative_file_paths:",
        f"    - {database.name}",
        "  duration:",
        f"    nanoseconds: {end - start}",
        "  starting_time:",
        f"    nanoseconds_since_epoch: {start}",
        f"  message_count: {message_count}",
        "  topics_with_message_count:",
    ]
    for name, msg_type, serialization, qos, count in topics:
        lines.extend(
            [
                "    - topic_metadata:",
                f"        name: {name}",
                f"        type: {msg_type}",
                f"        serialization_format: {serialization}",
                f"        offered_qos_profiles: {json.dumps(qos)}",
                f"      message_count: {count}",
            ]
        )
    lines.extend(['  compression_format: ""', '  compression_mode: ""'])
    (database.parent / "metadata.yaml").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge ROS2 sqlite bags by timestamp")
    parser.add_argument("output", type=Path)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(f"output already exists: {args.output}")
    input_dbs = [bag_db(path.resolve()) for path in args.inputs]

    args.output.mkdir(parents=True)
    output_db = args.output / "combined_0.db3"
    shutil.copy2(input_dbs[0], output_db)

    connection = sqlite3.connect(output_db)
    try:
        topics = {
            name: (topic_id, msg_type, serialization, qos)
            for topic_id, name, msg_type, serialization, qos in connection.execute(
                "SELECT id, name, type, serialization_format, offered_qos_profiles FROM topics"
            )
        }
        next_topic_id = max(topic[0] for topic in topics.values()) + 1

        for source_index, source_db in enumerate(input_dbs[1:], start=1):
            alias = f"source{source_index}"
            connection.execute(f"ATTACH DATABASE ? AS {alias}", (str(source_db),))
            source_topics = connection.execute(
                f"SELECT id, name, type, serialization_format, offered_qos_profiles "
                f"FROM {alias}.topics"
            ).fetchall()
            for source_topic_id, name, msg_type, serialization, qos in source_topics:
                if name in topics:
                    target_topic_id, old_type, old_serialization, _ = topics[name]
                    if (msg_type, serialization) != (old_type, old_serialization):
                        raise ValueError(f"incompatible duplicate topic: {name}")
                else:
                    target_topic_id = next_topic_id
                    next_topic_id += 1
                    connection.execute(
                        "INSERT INTO topics VALUES (?, ?, ?, ?, ?)",
                        (target_topic_id, name, msg_type, serialization, qos),
                    )
                    topics[name] = (target_topic_id, msg_type, serialization, qos)
                connection.execute(
                    f"INSERT INTO messages(topic_id, timestamp, data) "
                    f"SELECT ?, timestamp, data FROM {alias}.messages WHERE topic_id = ?",
                    (target_topic_id, source_topic_id),
                )
            connection.commit()
            connection.execute(f"DETACH DATABASE {alias}")

        result = connection.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"sqlite integrity check failed: {result}")
    finally:
        connection.close()
    write_metadata(output_db)


if __name__ == "__main__":
    main()
