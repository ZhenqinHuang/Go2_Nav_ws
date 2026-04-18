#!/usr/bin/env python3
"""
PTP 硬件时间同步启动节点

启动流程:
  1. [NTP 校准] 将本机系统时钟同步到互联网 NTP 标准时间
  2. [PTP 启动] 以 Master 模式启动 ptp4l / phc2sys，向 MID360 从机广播时间
  3. [状态监控] 持续发布同步状态到 ROS2 话题
"""

import os
import subprocess
import signal
import sys
import time
import re
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue

import yaml

# 导入 NTP 校准模块（scripts/ 目录与 go2_time_sync/ 同级）
_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'scripts'
)
sys.path.insert(0, _SCRIPTS_DIR)
from sync_host_time import load_ntp_config, run_ntp_sync  # noqa: E402


class PtpSyncNode(Node):
    def __init__(self):
        super().__init__('ptp_sync_node')

        # 声明参数
        self.declare_parameter('config_file', '')
        self.declare_parameter('skip_ntp', False)
        self.declare_parameter('ntp_dry_run', False)

        config_file = self.get_parameter('config_file').get_parameter_value().string_value
        if not config_file:
            # 默认配置文件路径
            config_file = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'config', 'ptp_sync.yaml'
            )

        self.get_logger().info(f'加载配置文件: {config_file}')
        self.config = self._load_config(config_file)

        self.interface = self.config['network']['interface']
        self.lidar_ip = self.config['lidar']['ip']

        skip_ntp = self.get_parameter('skip_ntp').get_parameter_value().bool_value
        ntp_dry_run = self.get_parameter('ntp_dry_run').get_parameter_value().bool_value

        # 发布者
        self.status_pub = self.create_publisher(String, '/ptp_sync/status', 10)
        self.synced_pub = self.create_publisher(Bool, '/ptp_sync/is_synced', 10)
        self.diag_pub = self.create_publisher(DiagnosticArray, '/diagnostics', 10)

        self.ptp4l_proc = None
        self.phc2sys_proc = None
        self._is_synced = False
        self._offset_ns = 0
        self._ntp_synced = False
        self._ntp_server_used = '—'
        self._ntp_offset_ms = 0.0

        # ── 步骤 1: NTP 本机时间校准 ──────────────
        if skip_ntp:
            self.get_logger().info('skip_ntp=true，跳过 NTP 校准步骤')
            self._ntp_synced = True  # 视为已完成
        else:
            self._do_ntp_calibration(config_file, ntp_dry_run)

        # 检查依赖
        self._check_dependencies()

        # ── 步骤 2: 启动 PTP ──────────────────────
        self._start_ptp()

        # 定时发布状态（1 Hz）
        self.create_timer(1.0, self._publish_status)

        self.get_logger().info(
            f'PTP Master 已启动 | 接口: {self.interface} | 雷达IP: {self.lidar_ip}'
        )

    # ──────────────────────────────────────────
    #  NTP 校准
    # ──────────────────────────────────────────

    def _do_ntp_calibration(self, config_file: str, dry_run: bool):
        """在 ROS2 节点初始化阶段同步执行 NTP 时间校准"""
        self.get_logger().info('=' * 50)
        self.get_logger().info('步骤 1/2 — 本机 NTP 时间校准')
        self.get_logger().info('=' * 50)

        try:
            ntp_cfg = load_ntp_config(config_file)

            if not ntp_cfg.get('enabled', True):
                self.get_logger().info('NTP 校准已禁用（配置 ntp.enabled=false）')
                self._ntp_synced = True
                return

            servers = ntp_cfg.get('servers', [])
            self.get_logger().info(f'NTP 服务器: {servers}')

            # 在独立线程中运行（不阻塞 ROS2 自旋，但 init 阶段实际是同步的）
            ok = run_ntp_sync(ntp_cfg, force=False, dry_run=dry_run, verbose=False)

            if ok:
                self.get_logger().info('NTP 时间校准成功 ✓')
                self._ntp_synced = True
            else:
                continue_on_failure = ntp_cfg.get('continue_on_failure', True)
                if continue_on_failure:
                    self.get_logger().warn('NTP 校准失败，但配置允许继续启动 PTP')
                    self._ntp_synced = False
                else:
                    self.get_logger().error('NTP 校准失败，配置要求终止')
                    sys.exit(1)

        except Exception as e:
            self.get_logger().warn(f'NTP 校准异常: {e}，继续启动 PTP')
            self._ntp_synced = False

        self.get_logger().info('步骤 1/2 完成')

    # ──────────────────────────────────────────
    #  配置 & 依赖
    # ──────────────────────────────────────────

    def _load_config(self, config_file: str) -> dict:
        with open(config_file, 'r') as f:
            return yaml.safe_load(f)

    def _check_dependencies(self):
        for cmd in ['ptp4l', 'phc2sys']:
            result = subprocess.run(['which', cmd], capture_output=True)
            if result.returncode != 0:
                self.get_logger().error(
                    f'未找到 {cmd}，请安装: sudo apt install linuxptp'
                )
                sys.exit(1)

        # 检测网卡是否支持硬件时间戳
        result = subprocess.run(
            ['ethtool', '-T', self.interface],
            capture_output=True, text=True
        )
        self._hw_ts = 'hardware-transmit' in result.stdout.lower()
        if self._hw_ts:
            self.get_logger().info(f'网卡 {self.interface} 支持硬件时间戳')
        else:
            self.get_logger().warn(
                f'网卡 {self.interface} 不支持硬件时间戳，使用软件时间戳'
            )

    # ──────────────────────────────────────────
    #  PTP 进程
    # ──────────────────────────────────────────

    def _build_ptp4l_cmd(self) -> list:
        cfg = self.config.get('ptp', {})
        ts_mode = 'hardware' if self._hw_ts else 'software'

        # 动态生成 ptp4l 配置文件（ptp4l 1.x 不支持长命令行选项）
        cfg_lines = [
            '[global]',
            f'domainNumber          {cfg.get("domain", 0)}',
            f'priority1             {cfg.get("priority1", 128)}',
            f'priority2             {cfg.get("priority2", 128)}',
            'clockClass            135',
            'clockAccuracy         0xFE',
            'offsetScaledLogVariance 0xFFFF',
            f'network_transport     {cfg.get("transport", "UDPv4")}',
            f'delay_mechanism       {cfg.get("delay_mechanism", "E2E")}',
            f'time_stamping         {ts_mode}',
            f'logSyncInterval       {cfg.get("log_sync_interval", 0)}',
            f'logAnnounceInterval   {cfg.get("log_announce_interval", 1)}',
            f'logMinDelayReqInterval {cfg.get("log_min_delay_req_interval", 0)}',
            'announceReceiptTimeout 3',
            f'twoStepFlag           {"0" if self._hw_ts else "1"}',
            'free_running          0',
            'summary_interval      1',
            f'[{self.interface}]',
        ]
        self._ptp4l_cfg_path = f'/tmp/ptp4l_{self.interface}.cfg'
        with open(self._ptp4l_cfg_path, 'w') as f:
            f.write('\n'.join(cfg_lines) + '\n')

        return ['ptp4l', '-f', self._ptp4l_cfg_path, '-m']

    def _start_ptp(self):
        self.get_logger().info('=' * 50)
        self.get_logger().info('步骤 2/2 — 启动 PTP Master (ptp4l + phc2sys)')
        self.get_logger().info('=' * 50)

        cmd = self._build_ptp4l_cmd()
        self.get_logger().info(f'启动 ptp4l: {" ".join(cmd)}')

        self.ptp4l_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid
        )

        # 后台线程读取 ptp4l 输出
        t = threading.Thread(target=self._read_ptp4l_output, daemon=True)
        t.start()

        # 等待 ptp4l 稳定后启动 phc2sys
        time.sleep(2.0)
        self._start_phc2sys()

    def _start_phc2sys(self):
        """phc2sys 将系统 CLOCK_REALTIME 同步到网卡 PHC（仅硬件时间戳模式需要）"""
        if not self._hw_ts:
            self.get_logger().info('软件时间戳模式，跳过 phc2sys（无 PHC 设备）')
            return

        cmd = [
            'phc2sys',
            '-s', 'CLOCK_REALTIME',   # 源：系统时钟
            '-c', self.interface,      # 目标：网卡 PHC
            '-O', '0',                 # UTC 偏移
            '-m',                      # 输出到 stdout
            '-q',
        ]
        self.get_logger().info(f'启动 phc2sys: {" ".join(cmd)}')

        self.phc2sys_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid
        )

        t = threading.Thread(target=self._read_phc2sys_output, daemon=True)
        t.start()

    def _read_ptp4l_output(self):
        # ptp4l 输出格式（软件时间戳 Master 模式）:
        #   ptp4l[T]: [interface] master offset <ns> s<state> freq <ppb> path delay <ns>
        #   ptp4l[T]: rms <ns> max <ns> freq <ppb> +/- <ppb> delay <ns> +/- <ns>
        offset_pattern = re.compile(r'master offset\s+(-?\d+)\s+s(\d+)')
        rms_pattern = re.compile(r'\brms\s+(\d+)\b')
        for line in self.ptp4l_proc.stdout:
            line = line.strip()
            if line:
                self.get_logger().debug(f'[ptp4l] {line}')
                m = offset_pattern.search(line)
                if m:
                    self._offset_ns = int(m.group(1))
                    state = int(m.group(2))
                    self._is_synced = (state >= 2 and abs(self._offset_ns) < 1000)
                    continue
                # summary_interval 行（rms 格式）
                m2 = rms_pattern.search(line)
                if m2:
                    self._offset_ns = int(m2.group(1))

    def _read_phc2sys_output(self):
        for line in self.phc2sys_proc.stdout:
            line = line.strip()
            if line:
                self.get_logger().debug(f'[phc2sys] {line}')

    # ──────────────────────────────────────────
    #  状态发布
    # ──────────────────────────────────────────

    def _publish_status(self):
        # 发布同步状态字符串
        status_msg = String()
        status_msg.data = (
            f'interface={self.interface} '
            f'lidar_ip={self.lidar_ip} '
            f'ntp_synced={self._ntp_synced} '
            f'synced={self._is_synced} '
            f'offset_ns={self._offset_ns}'
        )
        self.status_pub.publish(status_msg)

        # 发布布尔同步状态
        synced_msg = Bool()
        synced_msg.data = self._is_synced
        self.synced_pub.publish(synced_msg)

        # 发布诊断信息
        diag = DiagnosticArray()
        diag.header.stamp = self.get_clock().now().to_msg()
        status = DiagnosticStatus()
        status.name = 'PTP Sync'
        status.hardware_id = self.interface
        status.values = [
            KeyValue(key='interface', value=self.interface),
            KeyValue(key='lidar_ip', value=self.lidar_ip),
            KeyValue(key='ntp_synced', value=str(self._ntp_synced)),
            KeyValue(key='offset_ns', value=str(self._offset_ns)),
            KeyValue(key='synced', value=str(self._is_synced)),
        ]
        if self._is_synced:
            status.level = DiagnosticStatus.OK
            status.message = f'同步正常，偏移 {self._offset_ns} ns（NTP已校准: {self._ntp_synced}）'
        else:
            status.level = DiagnosticStatus.WARN
            status.message = f'等待同步，偏移 {self._offset_ns} ns（NTP已校准: {self._ntp_synced}）'
        diag.status.append(status)
        self.diag_pub.publish(diag)

    def destroy_node(self):
        self.get_logger().info('停止 PTP 进程...')
        for proc in [self.ptp4l_proc, self.phc2sys_proc]:
            if proc and proc.poll() is None:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=5)
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PtpSyncNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
