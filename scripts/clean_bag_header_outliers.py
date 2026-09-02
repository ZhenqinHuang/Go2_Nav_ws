#!/usr/bin/env python3
import argparse
import sqlite3
import struct
from pathlib import Path

from merge_rosbags import write_metadata


def header_stamp(data: bytes) -> int:
    if len(data) < 12:
        raise ValueError("CDR message is too short")
    encoding = int.from_bytes(data[:2], "big")
    byte_order = "<" if encoding in (1, 3) else ">"
    sec, nanosec = struct.unpack_from(f"{byte_order}iI", data, 4)
    return sec * 1_000_000_000 + nanosec


def main() -> None:
    parser = argparse.ArgumentParser(description="Find or remove bad ROS header stamps")
    parser.add_argument("database", type=Path)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--max-offset", type=float, default=0.5)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    connection = sqlite3.connect(args.database)
    try:
        rows = connection.execute(
            "SELECT m.id, m.timestamp, m.data FROM messages m "
            "JOIN topics t ON t.id = m.topic_id WHERE t.name = ? "
            "ORDER BY m.timestamp",
            (args.topic,),
        ).fetchall()
        outliers = []
        for message_id, timestamp, data in rows:
            offset = (timestamp - header_stamp(data)) / 1_000_000_000
            if abs(offset) > args.max_offset:
                outliers.append((message_id, offset))

        print(f"topic={args.topic} messages={len(rows)} outliers={len(outliers)}")
        for message_id, offset in outliers:
            print(f"id={message_id} offset_seconds={offset:.6f}")

        if args.apply and outliers:
            connection.executemany(
                "DELETE FROM messages WHERE id = ?",
                [(message_id,) for message_id, _ in outliers],
            )
            connection.commit()
            result = connection.execute("PRAGMA quick_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"sqlite integrity check failed: {result}")
    finally:
        connection.close()

    if args.apply and outliers:
        write_metadata(args.database)


if __name__ == "__main__":
    main()
