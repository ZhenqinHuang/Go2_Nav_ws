#!/usr/bin/env python3
"""Motion-free UDP integration test for go2_cmd_gateway."""

import argparse
import socket
import struct
import subprocess
import sys
import time
import zlib


MAGIC = 0x47324757
VERSION = 1
CONTROL = 1
ACK = 2
FRAME_SIZE = 56
LOCKED = 0
WATCHDOG = 1


def control_frame(session, sequence, token, flags=0, vx=0.0, vy=0.0, vyaw=0.0):
    body = struct.pack(
        "!IHHHHQQQIfff",
        MAGIC,
        VERSION,
        CONTROL,
        FRAME_SIZE,
        0,
        session,
        sequence,
        token,
        flags,
        vx,
        vy,
        vyaw,
    )
    return body + struct.pack("!I", zlib.crc32(body) & 0xFFFFFFFF)


def decode_ack(payload):
    assert len(payload) == FRAME_SIZE, f"ACK length {len(payload)}"
    assert zlib.crc32(payload[:-4]) & 0xFFFFFFFF == struct.unpack(
        "!I", payload[-4:]
    )[0]
    values = struct.unpack("!IHHHHQQQIiIII", payload)
    assert values[:5] == (MAGIC, VERSION, ACK, FRAME_SIZE, 0)
    return {
        "session": values[5],
        "sequence": values[6],
        "token": values[7],
        "state": values[8],
        "sdk_code": values[9],
        "fault": values[10],
        "flags": values[11],
    }


def free_udp_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def receive_ack(sock, *, timeout=0.4):
    sock.settimeout(timeout)
    payload, source = sock.recvfrom(2048)
    return decode_ack(payload), source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", required=True)
    arguments = parser.parse_args()

    port = free_udp_port()
    try:
        process = subprocess.Popen(
            [
                arguments.gateway,
                "--dry-run",
                "--bind",
                "127.0.0.1",
                "--port",
                str(port),
                "--allowed-ip",
                "127.0.0.1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as error:
        print(f"failed to launch gateway: {error}", file=sys.stderr)
        return 1

    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.bind(("127.0.0.1", 0))
    destination = ("127.0.0.1", port)
    session = 0x101
    try:
        time.sleep(0.08)
        if process.poll() is not None:
            stderr = process.stderr.read()
            raise AssertionError(f"gateway exited early: {stderr}")

        client.sendto(control_frame(session, 1, 0), destination)
        ack, source = receive_ack(client)
        assert source == destination
        assert ack["session"] == session and ack["sequence"] == 1
        assert ack["state"] == LOCKED

        corrupted = bytearray(
            control_frame(session, 2, 0, vx=0.2)
        )
        corrupted[20] ^= 0x01
        client.sendto(corrupted, destination)
        try:
            receive_ack(client, timeout=0.12)
            raise AssertionError("invalid CRC unexpectedly received an ACK")
        except socket.timeout:
            pass

        sequence = 2
        client.sendto(
            control_frame(session, sequence, 0, vx=0.2), destination
        )
        ack, _ = receive_ack(client)
        assert ack["sequence"] == sequence and ack["state"] == LOCKED
        assert ack["token"] == 0

        timeout_ack, source = receive_ack(client, timeout=0.8)
        assert source == destination
        assert timeout_ack["state"] == LOCKED
        assert timeout_ack["fault"] == WATCHDOG
        assert timeout_ack["token"] == 0

        client.sendto(
            control_frame(session, sequence + 1, 0x202, 1),
            destination,
        )
        try:
            receive_ack(client, timeout=0.15)
            raise AssertionError("legacy Arm request unexpectedly received ACK")
        except socket.timeout:
            pass

        print("udp_integration_test: PASS")
        return 0
    finally:
        client.close()
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1.0)


if __name__ == "__main__":
    raise SystemExit(main())
