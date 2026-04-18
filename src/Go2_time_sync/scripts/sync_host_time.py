#!/usr/bin/env python3
"""
本机 NTP 时间校准脚本（独立使用，无需 ROS2）

功能：
  1. 依次查询多个 NTP 服务器，获取准确的网络时间
  2. 比较本机时间与网络时间的偏差
  3. 若偏差超过阈值（或强制模式），调用 date 命令更新系统时钟
  4. 输出详细校准报告

用法:
  sudo python3 scripts/sync_host_time.py [--config config/ptp_sync.yaml] [--force] [--dry-run]

选项:
  --config    配置文件路径（默认使用 config/ptp_sync.yaml）
  --force     强制校准，忽略偏差阈值
  --dry-run   仅检测时间偏差，不实际修改系统时钟
"""

import argparse
import os
import socket
import struct
import sys
import time
import datetime
from typing import List, Optional, Tuple

import yaml


# ──────────────────────────────────────────────
#  SNTP / NTP 协议常量
# ──────────────────────────────────────────────
NTP_PORT = 123
NTP_EPOCH_DELTA = 2208988800  # 1900-01-01 → 1970-01-01 (Unix Epoch) 的秒数
NTP_PACKET_FORMAT = '!12I'
NTP_PACKET_SIZE = 48


def _make_ntp_request() -> bytes:
    """构造 NTPv3 客户端请求包（48 字节）"""
    packet = bytearray(NTP_PACKET_SIZE)
    # LI=0, VN=3, Mode=3 (client)
    packet[0] = 0b00011011
    return bytes(packet)


def query_ntp_server(server: str, timeout: int = 5) -> Optional[float]:
    """
    向单个 NTP 服务器查询当前 UTC 时间（Unix 时间戳，秒）。

    返回 float 时间戳，失败返回 None。
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)

        request = _make_ntp_request()
        send_time = time.time()
        sock.sendto(request, (server, NTP_PORT))

        data, _ = sock.recvfrom(1024)
        recv_time = time.time()

        if len(data) < NTP_PACKET_SIZE:
            return None

        # 解析 Transmit Timestamp（字节 40-47）
        tx_sec, tx_frac = struct.unpack('!II', data[40:48])
        ntp_ts = tx_sec - NTP_EPOCH_DELTA + tx_frac / (2 ** 32)

        # 使用往返时间中点校正（Round-Trip Time / 2）
        rtt = recv_time - send_time
        corrected_ts = ntp_ts + rtt / 2.0
        return corrected_ts

    except (socket.timeout, socket.gaierror, OSError):
        return None
    finally:
        try:
            sock.close()
        except Exception:
            pass


def get_network_time(servers: List[str], timeout: int = 5,
                     retry_count: int = 2) -> Tuple[Optional[float], str]:
    """
    依次尝试多个 NTP 服务器，返回第一个成功的网络时间和使用的服务器名。

    返回 (timestamp_or_None, server_name_or_reason)
    """
    for attempt in range(retry_count + 1):
        if attempt > 0:
            print(f'[NTP] 第 {attempt + 1} 轮重试...')
        for server in servers:
            print(f'[NTP] 正在查询 {server} ...', end=' ', flush=True)
            ts = query_ntp_server(server, timeout=timeout)
            if ts is not None:
                print(f'成功  (延迟校正后 UTC: {datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]})')
                return ts, server
            else:
                print('超时或失败')
    return None, '所有 NTP 服务器均无法访问'


def set_system_time(timestamp: float) -> bool:
    """
    将系统时钟设置为给定的 Unix 时间戳（需要 root 权限）。
    使用 date 命令以 UTC 格式写入。
    返回是否成功。
    """
    import subprocess
    dt_utc = datetime.datetime.utcfromtimestamp(timestamp)
    # date 命令格式：MMDDHHmmYYYY.SS
    date_str = dt_utc.strftime('%m%d%H%M%Y.%S')
    result = subprocess.run(
        ['date', '-u', date_str],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return True
    else:
        print(f'[错误] date 命令失败: {result.stderr.strip()}')
        return False


def sync_rtc_from_system() -> bool:
    """将系统时钟写入硬件 RTC（hwclock），防止重启后时间回退（需要 root）"""
    import subprocess
    result = subprocess.run(
        ['hwclock', '--systohc'],
        capture_output=True, text=True
    )
    return result.returncode == 0


def load_ntp_config(config_path: str) -> dict:
    """从 YAML 配置文件中读取 ntp 节，失败时返回默认值"""
    defaults = {
        'enabled': True,
        'servers': [
            'ntp.aliyun.com',
            'cn.pool.ntp.org',
            'time1.cloud.tencent.com',
            'time.windows.com',
            'pool.ntp.org',
        ],
        'timeout': 5,
        'max_offset_seconds': 1.0,
        'retry_count': 2,
        'continue_on_failure': True,
    }
    if not os.path.isfile(config_path):
        print(f'[NTP] 配置文件不存在: {config_path}，使用默认参数')
        return defaults

    with open(config_path, 'r') as f:
        cfg = yaml.safe_load(f)

    ntp_cfg = cfg.get('ntp', {})
    # 合并默认值
    for k, v in defaults.items():
        ntp_cfg.setdefault(k, v)
    return ntp_cfg


def check_root():
    if os.geteuid() != 0:
        print('[错误] 修改系统时钟需要 root 权限，请使用 sudo 运行')
        sys.exit(1)


# ──────────────────────────────────────────────
#  主流程
# ──────────────────────────────────────────────

def run_ntp_sync(ntp_cfg: dict, force: bool = False, dry_run: bool = False,
                 verbose: bool = True) -> bool:
    """
    执行 NTP 时间校准。

    参数:
        ntp_cfg:  从配置文件解析的 ntp 节字典
        force:    True = 忽略偏差阈值，始终更新时钟
        dry_run:  True = 仅检测，不修改系统时钟
        verbose:  是否输出详细日志

    返回:
        True  - 时间同步成功（或已在容差范围内无需校准）
        False - 同步失败
    """
    if not ntp_cfg.get('enabled', True):
        if verbose:
            print('[NTP] NTP 校准已禁用（配置 ntp.enabled=false），跳过')
        return True

    servers = ntp_cfg.get('servers', [])
    timeout = int(ntp_cfg.get('timeout', 5))
    max_offset = float(ntp_cfg.get('max_offset_seconds', 1.0))
    retry_count = int(ntp_cfg.get('retry_count', 2))
    continue_on_failure = bool(ntp_cfg.get('continue_on_failure', True))

    if not servers:
        print('[NTP] 服务器列表为空，跳过校准')
        return True

    if verbose:
        print('=' * 60)
        print('  步骤 1/2 — 本机 NTP 时间校准')
        print('=' * 60)

    local_ts = time.time()
    local_dt = datetime.datetime.utcfromtimestamp(local_ts)
    if verbose:
        print(f'[NTP] 当前本机时间 (UTC): {local_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]}')
        print(f'[NTP] 服务器列表: {servers}')

    # 查询网络时间
    net_ts, used_server = get_network_time(servers, timeout=timeout, retry_count=retry_count)

    if net_ts is None:
        print(f'[NTP] ⚠ 无法获取网络时间: {used_server}')
        if continue_on_failure:
            print('[NTP] 配置允许在 NTP 失败时继续，跳过时钟校准')
            return True
        else:
            print('[NTP] 配置要求 NTP 成功后才能继续，终止')
            return False

    offset = net_ts - local_ts
    offset_ms = offset * 1000.0
    net_dt = datetime.datetime.utcfromtimestamp(net_ts)

    if verbose:
        print(f'[NTP] 网络时间 (UTC): {net_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]}  (来源: {used_server})')
        print(f'[NTP] 本机偏差: {offset_ms:+.3f} ms  ({offset:+.6f} s)')

    need_update = force or (max_offset == 0) or (abs(offset) > max_offset)

    if not need_update:
        if verbose:
            print(f'[NTP] ✓ 本机时间误差 {abs(offset_ms):.1f} ms，在容差范围 '
                  f'({max_offset * 1000:.0f} ms) 内，无需校准')
        return True

    if dry_run:
        if verbose:
            print(f'[NTP] [DRY-RUN] 需要校准，但 --dry-run 模式不修改系统时钟')
        return True

    # 实际写入系统时钟
    print(f'[NTP] 正在将系统时钟调整 {offset_ms:+.3f} ms ...')
    ok = set_system_time(net_ts)
    if ok:
        print(f'[NTP] ✓ 系统时钟已更新至网络时间')
        # 同步到硬件 RTC
        if sync_rtc_from_system():
            print('[NTP] ✓ 硬件 RTC 已同步')
        else:
            print('[NTP] ⚠ hwclock 同步失败（非致命，可忽略）')
    else:
        print('[NTP] ✗ 系统时钟更新失败')
        if not continue_on_failure:
            return False

    return ok or continue_on_failure


def main():
    parser = argparse.ArgumentParser(
        description='本机 NTP 时间校准工具（须以 root 运行）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  sudo python3 scripts/sync_host_time.py
  sudo python3 scripts/sync_host_time.py --force
  sudo python3 scripts/sync_host_time.py --dry-run
  sudo python3 scripts/sync_host_time.py --config /path/to/ptp_sync.yaml
        """
    )
    default_cfg = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'config', 'ptp_sync.yaml'
    )
    parser.add_argument('--config', default=default_cfg, help='配置文件路径')
    parser.add_argument('--force', action='store_true',
                        help='强制校准，忽略偏差阈值')
    parser.add_argument('--dry-run', action='store_true',
                        help='仅检测偏差，不修改系统时钟')
    args = parser.parse_args()

    if not args.dry_run:
        check_root()

    ntp_cfg = load_ntp_config(args.config)
    success = run_ntp_sync(ntp_cfg, force=args.force, dry_run=args.dry_run)

    if success:
        print('[NTP] 时间校准完成 ✓')
        sys.exit(0)
    else:
        print('[NTP] 时间校准失败 ✗')
        sys.exit(1)


if __name__ == '__main__':
    main()
