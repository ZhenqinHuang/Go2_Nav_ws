import importlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from go2_control_gateway.protocol import (  # noqa: E402
    AckFlags,
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


class FailingBindSocket(FakeSocket):
    def bind(self, address):
        self.bound = address
        raise OSError(99, "address not available")


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


def locked_ack(packet):
    return AckFrame(
        session_id=packet.session_id,
        sequence=packet.sequence,
        arm_token=0,
        state=GatewayState.LOCKED,
        sdk_code=0,
        fault=FaultReason.NONE,
    )


def establish_link(adapter, fake_socket):
    adapter.send_once()
    packet = decode_control(fake_socket.sent[-1][0])
    assert adapter.handle_datagram(
        encode_ack(locked_ack(packet)),
        ("192.168.123.18", 15000),
    )


def test_defaults_bind_dedicated_control_interface_at_20_hz():
    module = load_adapter()
    adapter, _core, fake_socket, _clock = make_adapter(module)

    assert fake_socket.bound == ("192.168.123.5", 15001)
    assert adapter.destination == ("192.168.123.18", 15000)
    assert adapter.send_period_sec == pytest.approx(0.05)


def test_send_once_serializes_token_zero_frame_to_internal_gateway():
    module = load_adapter()
    adapter, _core, fake_socket, _clock = make_adapter(module)

    adapter.send_once()

    payload, destination = fake_socket.sent[-1]
    packet = decode_control(payload)
    assert destination == ("192.168.123.18", 15000)
    assert packet.session_id == 101
    assert packet.sequence == 1
    assert packet.arm_token == 0
    assert packet.flags == ControlFlags.NONE


def test_ack_receiver_filters_source_and_marks_control_ready():
    module = load_adapter()
    adapter, core, fake_socket, _clock = make_adapter(module)
    adapter.send_once()
    packet = decode_control(fake_socket.sent[-1][0])
    payload = encode_ack(locked_ack(packet))

    assert not adapter.handle_datagram(payload, ("192.168.123.99", 15000))
    assert not core.control_ready
    assert adapter.handle_datagram(payload, ("192.168.123.18", 15000))
    assert core.control_ready


def test_manual_velocity_is_sent_after_link_ack_without_arm():
    module = load_adapter()
    adapter, _core, fake_socket, _clock = make_adapter(module)
    establish_link(adapter, fake_socket)

    assert adapter.update_manual_cmd(0.2, 0.0, 0.0)
    adapter.send_once()
    packet = decode_control(fake_socket.sent[-1][0])

    assert packet.vx == pytest.approx(0.2)
    assert packet.arm_token == 0
    assert packet.flags == ControlFlags.NONE


def test_status_json_contains_ready_state_but_no_arm_or_secret():
    module = load_adapter()
    adapter, _core, fake_socket, _clock = make_adapter(module)
    establish_link(adapter, fake_socket)

    status_text = adapter.status_json()
    status = json.loads(status_text)

    assert status["gateway_link"] == "online"
    assert status["control_ready"] is True
    assert status["nav_active"] is False
    assert "armed" not in status
    assert "password" not in status_text.lower()
    assert "secret" not in status_text.lower()
    assert "token" not in status_text.lower()


def test_shutdown_repeats_plain_zero_frames():
    module = load_adapter()
    adapter, _core, fake_socket, _clock = make_adapter(module)
    establish_link(adapter, fake_socket)
    adapter.update_manual_cmd(0.2, 0.0, 0.0)
    sent_before = len(fake_socket.sent)

    adapter.shutdown(repeat_count=3, repeat_interval_sec=0.0)

    shutdown_packets = [
        decode_control(payload)
        for payload, _destination in fake_socket.sent[sent_before:]
    ]
    assert len(shutdown_packets) == 3
    assert all(packet.flags == ControlFlags.NONE for packet in shutdown_packets)
    assert all(packet.arm_token == 0 for packet in shutdown_packets)
    assert all(
        (packet.vx, packet.vy, packet.vyaw) == (0.0, 0.0, 0.0)
        for packet in shutdown_packets
    )
    assert fake_socket.closed


def test_adapter_exposes_latched_estop_reset_and_posture_commands():
    module = load_adapter()
    adapter, core, fake_socket, _clock = make_adapter(module)
    establish_link(adapter, fake_socket)

    assert adapter.request_emergency_stop()
    adapter.send_once()
    stop_packet = decode_control(fake_socket.sent[-1][0])
    assert stop_packet.flags == ControlFlags.EMERGENCY_STOP
    assert adapter.handle_datagram(
        encode_ack(
            AckFrame(
                session_id=stop_packet.session_id,
                sequence=stop_packet.sequence,
                arm_token=0,
                state=GatewayState.LOCKED,
                sdk_code=0,
                fault=FaultReason.ESTOP,
                flags=AckFlags.ESTOP_LATCHED | AckFlags.COMMAND_ACCEPTED,
            )
        ),
        adapter.destination,
    )
    assert core.estop_latched

    assert adapter.request_reset_emergency_stop()
    adapter.send_once()
    reset_packet = decode_control(fake_socket.sent[-1][0])
    assert reset_packet.flags == ControlFlags.RESET_ESTOP
    assert adapter.handle_datagram(
        encode_ack(
            AckFrame(
                session_id=reset_packet.session_id,
                sequence=reset_packet.sequence,
                arm_token=0,
                state=GatewayState.LOCKED,
                sdk_code=0,
                fault=FaultReason.NONE,
                flags=AckFlags.COMMAND_ACCEPTED,
            )
        ),
        adapter.destination,
    )
    assert not core.estop_latched

    assert adapter.request_posture("stand")
    adapter.send_once()
    stand_packet = decode_control(fake_socket.sent[-1][0])
    assert stand_packet.flags == ControlFlags.STAND


def test_status_json_reports_single_control_state_and_exact_block_reason():
    module = load_adapter()
    adapter, _core, fake_socket, _clock = make_adapter(module)

    offline = json.loads(adapter.status_json())
    assert offline["control_ready"] is False
    assert offline["block_reason"] == "gateway_ack_stale"
    assert offline["active_source"] == "idle"
    assert offline["estop_latched"] is False
    assert offline["posture"] == "unknown"
    assert "localization_ready" in offline

    establish_link(adapter, fake_socket)
    ready = json.loads(adapter.status_json())
    assert ready["control_ready"] is True
    assert ready["block_reason"] is None

    adapter.request_emergency_stop()
    stopped = json.loads(adapter.status_json())
    assert stopped["control_ready"] is False
    assert stopped["block_reason"] == "estop_latched"
    assert stopped["active_source"] == "emergency_stop"


def test_missing_control_address_enters_wait_state_and_recovers_without_restart():
    module = load_adapter()
    clock = FakeClock()
    failed_socket = FailingBindSocket()
    recovered_socket = FakeSocket()
    sockets = iter((failed_socket, recovered_socket))
    core = SenderCore(
        config=SenderConfig(localization_guard_enabled=False),
        clock=clock,
        session_id=101,
    )
    adapter = module.UdpSenderAdapter(
        core=core,
        config=module.NetworkConfig(bind_retry_sec=5.0),
        socket_factory=lambda *_args: next(sockets),
        clock=clock,
        waiter=clock.wait,
    )

    waiting = json.loads(adapter.status_json())
    assert waiting["network_ready"] is False
    assert waiting["block_reason"] == "control_network_unavailable"
    with pytest.raises(OSError):
        adapter.send_once()

    clock.wait(5.0)
    assert adapter.send_once() > 0
    assert recovered_socket.bound == ("192.168.123.5", 15001)


def test_ros_node_exposes_only_gateway_backed_posture_and_estop_services():
    source = (PACKAGE_ROOT / "go2_control_gateway" / "udp_sender_node.py").read_text(
        encoding="utf-8"
    )

    for service in (
        "/go2_cmd_vel_gateway/stand_up",
        "/go2_cmd_vel_gateway/stand_down",
        "/go2_cmd_vel_gateway/emergency_stop",
        "/go2_cmd_vel_gateway/reset_emergency_stop",
    ):
        assert service in source
    assert "/api/sport/request" not in source
