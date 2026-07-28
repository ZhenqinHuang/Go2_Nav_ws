import importlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from go2_control_gateway.protocol import (  # noqa: E402
    AckFrame,
    ControlFlags,
    FaultReason,
    GatewayState,
    decode_control,
    encode_ack,
)
from go2_control_gateway.sender_core import SenderConfig, SenderCore  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def wait(self, seconds):
        self.now += seconds


class FakeSocket:
    def __init__(self):
        self.bound = None
        self.timeout = None
        self.sent = []
        self.closed = False

    def bind(self, address):
        self.bound = address

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendto(self, payload, destination):
        self.sent.append((payload, destination))
        return len(payload)

    def close(self):
        self.closed = True


def load_adapter():
    spec = importlib.util.find_spec("go2_control_gateway.udp_sender_node")
    if spec is None:
        pytest.fail("udp_sender_node module is missing")
    return importlib.import_module("go2_control_gateway.udp_sender_node")


def make_adapter(module, *, clock=None):
    clock = clock or FakeClock()
    fake_socket = FakeSocket()
    core = SenderCore(
        config=SenderConfig(localization_guard_enabled=False),
        clock=clock,
        token_source=iter([201, 202, 203]).__next__,
        session_id=101,
    )
    adapter = module.UdpSenderAdapter(
        core=core,
        config=module.NetworkConfig(),
        socket_factory=lambda *_args: fake_socket,
        clock=clock,
        waiter=clock.wait,
    )
    return adapter, core, fake_socket, clock


def armed_ack(packet):
    return AckFrame(
        session_id=packet.session_id,
        sequence=packet.sequence,
        arm_token=packet.arm_token,
        state=GatewayState.ARMED,
        sdk_code=0,
        fault=FaultReason.NONE,
    )


def arm_over_adapter(adapter, core, fake_socket):
    core.request_arm()
    adapter.send_once()
    packet = decode_control(fake_socket.sent[-1][0])
    assert adapter.handle_datagram(
        encode_ack(armed_ack(packet)),
        ("192.168.123.18", 15000),
    )
    assert core.is_armed


def test_defaults_bind_dedicated_control_interface_at_20_hz():
    module = load_adapter()
    adapter, _core, fake_socket, _clock = make_adapter(module)

    assert fake_socket.bound == ("192.168.123.5", 15001)
    assert adapter.destination == ("192.168.123.18", 15000)
    assert adapter.send_period_sec == pytest.approx(0.05)


def test_send_once_serializes_control_frame_to_internal_gateway():
    module = load_adapter()
    adapter, _core, fake_socket, _clock = make_adapter(module)

    adapter.send_once()

    payload, destination = fake_socket.sent[-1]
    packet = decode_control(payload)
    assert destination == ("192.168.123.18", 15000)
    assert packet.session_id == 101
    assert packet.sequence == 1


def test_ack_receiver_filters_source_and_updates_sender_core():
    module = load_adapter()
    adapter, core, fake_socket, _clock = make_adapter(module)
    core.request_arm()
    adapter.send_once()
    packet = decode_control(fake_socket.sent[-1][0])
    payload = encode_ack(armed_ack(packet))

    assert not adapter.handle_datagram(payload, ("192.168.123.99", 15000))
    assert not core.is_armed
    assert adapter.handle_datagram(payload, ("192.168.123.18", 15000))
    assert core.is_armed


def test_locked_heartbeat_ack_marks_link_online_without_arming():
    module = load_adapter()
    adapter, core, fake_socket, _clock = make_adapter(module)
    adapter.send_once()
    packet = decode_control(fake_socket.sent[-1][0])
    locked_ack = AckFrame(
        session_id=packet.session_id,
        sequence=packet.sequence,
        arm_token=0,
        state=GatewayState.LOCKED,
        sdk_code=0,
        fault=FaultReason.NONE,
    )

    assert adapter.handle_datagram(
        encode_ack(locked_ack), ("192.168.123.18", 15000)
    )
    assert not core.is_armed
    assert json.loads(adapter.status_json())["gateway_link"] == "online"


def test_arm_wait_is_bounded_to_one_second_without_matching_ack():
    module = load_adapter()
    adapter, core, _fake_socket, clock = make_adapter(module)

    expected_token = 201
    result = adapter.request_arm(timeout_sec=5.0)

    assert not result
    assert not core.is_armed
    assert core.arm_token == 0
    assert expected_token in core.revoked_tokens
    assert 1.0 <= clock.now <= 1.01


def test_status_json_contains_operational_state_but_no_secret_or_token():
    module = load_adapter()
    adapter, core, fake_socket, _clock = make_adapter(module)
    arm_over_adapter(adapter, core, fake_socket)

    status_text = adapter.status_json()
    status = json.loads(status_text)

    assert status["gateway_link"] == "online"
    assert status["armed"] is True
    assert status["nav_active"] is False
    assert "password" not in status_text.lower()
    assert "secret" not in status_text.lower()
    assert "token" not in status_text.lower()
    assert "201" not in status_text


def test_shutdown_repeats_disarm_zero_frames():
    module = load_adapter()
    adapter, core, fake_socket, _clock = make_adapter(module)
    arm_over_adapter(adapter, core, fake_socket)
    sent_before = len(fake_socket.sent)

    adapter.shutdown(repeat_count=3, repeat_interval_sec=0.0)

    shutdown_packets = [
        decode_control(payload)
        for payload, _destination in fake_socket.sent[sent_before:]
    ]
    assert len(shutdown_packets) == 3
    assert all(packet.flags == ControlFlags.DISARM for packet in shutdown_packets)
    assert all(
        (packet.vx, packet.vy, packet.vyaw) == (0.0, 0.0, 0.0)
        for packet in shutdown_packets
    )
    assert fake_socket.closed
