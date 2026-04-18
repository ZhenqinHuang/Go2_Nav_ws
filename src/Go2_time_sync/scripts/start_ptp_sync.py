#!/usr/bin/env python3
"""
PTP 同步启动脚本（非 ROS2，直接命令行使用）

流程:
  步骤 1/2 — 本机 NTP 时间校准（将系统时钟同步到网络标准时间）
  步骤 2/2 — 启动 PTP Master（将系统时钟→PHC→MID360 从机）

用法:
  sudo python3 scripts/start_ptp_sync.py [--config config/ptp_sync.yaml]
  sudo python3 scripts/start_ptp_sync.py --skip-ntp      # 跳过 NTP 校准直接启 PTP
  sudo python3 scripts/start_ptp_sync.py --ntp-dry-run   # NTP 仅检测不修改时钟
"""

import argparse
import os
import signal
import subprocess
import sys
import time

import yaml

# 导入同目录的 NTP 校准模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync_host_time import load_ntp_config, run_ntp_sync  # noqa: E402


# ──────────────────────────────────────────────
#  基础工具函数
# ──────────────────────────────────────────────

def load_config(path: str) -> dict:
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def check_root():
    if os.geteuid() != 0:
        print('[错误] ptp4l / 系统时钟修改均需要 root 权限，请使用 sudo 运行')
        sys.exit(1)


def check_deps():
    for cmd in ['ptp4l', 'phc2sys', 'ethtool']:
        r = subprocess.run(['which', cmd], capture_output=True)
        if r.returncode != 0:
            print(f'[错误] 未找到 {cmd}，请安装: sudo apt install linuxptp ethtool')
            sys.exit(1)


def check_hw_timestamp(iface: str) -> bool:
    r = subprocess.run(['ethtool', '-T', iface], capture_output=True, text=True)
    if r.returncode != 0:
        print(f'[警告] 无法查询 {iface} 时间戳能力: {r.stderr.strip()}')
        return False
    if 'hardware-transmit' in r.stdout.lower():
        print(f'[OK] {iface} 支持硬件时间戳')
        return True
    else:
        print(f'[警告] {iface} 不支持硬件时间戳，将使用软件时间戳')
        return False


def write_ptp4l_cfg(config: dict, hw_ts: bool) -> str:
    """生成 ptp4l 配置文件，返回路径（ptp4l 1.x 不支持长命令行选项）"""
    iface = config['network']['interface']
    ptp = config.get('ptp', {})
    ts_mode = 'hardware' if hw_ts else 'software'

    lines = [
        '[global]',
        f'domainNumber          {ptp.get("domain", 0)}',
        f'priority1             {ptp.get("priority1", 128)}',
        f'priority2             {ptp.get("priority2", 128)}',
        'clockClass            135',
        'clockAccuracy         0xFE',
        'offsetScaledLogVariance 0xFFFF',
        f'network_transport     {ptp.get("transport", "UDPv4")}',
        f'delay_mechanism       {ptp.get("delay_mechanism", "E2E")}',
        f'time_stamping         {ts_mode}',
        f'logSyncInterval       {ptp.get("log_sync_interval", 0)}',
        f'logAnnounceInterval   {ptp.get("log_announce_interval", 1)}',
        f'logMinDelayReqInterval {ptp.get("log_min_delay_req_interval", 0)}',
        'announceReceiptTimeout 3',
        'twoStepFlag           0',
        'free_running          0',
        'summary_interval      1',
        f'[{iface}]',
    ]
    cfg_path = f'/tmp/ptp4l_{iface}.cfg'
    with open(cfg_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return cfg_path


# ──────────────────────────────────────────────
#  PTP 进程启动
# ──────────────────────────────────────────────

def start_ptp_master(config: dict, hw_ts: bool):
    iface = config['network']['interface']

    cfg_path = write_ptp4l_cfg(config, hw_ts)
    ptp4l_cmd = ['ptp4l', '-f', cfg_path, '-m']

    print(f'\n[启动] ptp4l Master 模式 | 接口: {iface} | 时间戳: {"hardware" if hw_ts else "software"}')
    print(f'       命令: {" ".join(ptp4l_cmd)}')
    ptp4l_proc = subprocess.Popen(ptp4l_cmd, preexec_fn=os.setsid)

    phc2sys_proc = None
    if hw_ts:
        time.sleep(3)
        # phc2sys: 系统时钟 -> PHC（仅硬件时间戳模式需要）
        phc2sys_cmd = [
            'phc2sys',
            '-s', 'CLOCK_REALTIME',
            '-c', iface,
            '-O', '0',
            '-m',
            '-q',
        ]
        print(f'[启动] phc2sys (系统时钟 -> PHC) | 命令: {" ".join(phc2sys_cmd)}')
        phc2sys_proc = subprocess.Popen(phc2sys_cmd, preexec_fn=os.setsid)
    else:
        print('[信息] 软件时间戳模式，跳过 phc2sys（无 PHC 设备）')

    return ptp4l_proc, phc2sys_proc


# ──────────────────────────────────────────────
#  主流程
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='PTP Master 时间同步启动脚本（含 NTP 本机校准）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
流程说明:
  1. [NTP 校准] 将本机系统时钟同步到互联网 NTP 时间（保证时间基准准确）
  2. [PTP 启动] 以 ptp4l Master 模式广播精确时间给 MID360 从机
        """
    )
    default_cfg = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'config', 'ptp_sync.yaml'
    )
    parser.add_argument('--config', default=default_cfg, help='配置文件路径')
    parser.add_argument('--skip-ntp', action='store_true',
                        help='跳过 NTP 校准步骤，直接启动 PTP')
    parser.add_argument('--ntp-dry-run', action='store_true',
                        help='NTP 仅检测偏差，不实际修改系统时钟')
    args = parser.parse_args()

    check_root()
    check_deps()

    config = load_config(args.config)
    iface = config['network']['interface']
    lidar_ip = config['lidar']['ip']

    print('=' * 60)
    print('         Go2 时间同步系统启动')
    print('=' * 60)
    print(f'[配置] 网卡: {iface}  雷达IP: {lidar_ip}')
    print(f'[配置] 配置文件: {args.config}')

    # ── 步骤 1: NTP 本机时间校准 ──────────────────
    if args.skip_ntp:
        print('\n[跳过] --skip-ntp 已指定，跳过 NTP 校准步骤')
    else:
        ntp_cfg = load_ntp_config(args.config)
        ntp_ok = run_ntp_sync(
            ntp_cfg,
            force=False,
            dry_run=args.ntp_dry_run,
            verbose=True
        )
        if not ntp_ok:
            print('\n[错误] NTP 校准失败且配置要求不继续，程序退出')
            sys.exit(1)
        print()  # 空行分隔两步骤

    # ── 步骤 2: 启动 PTP Master ───────────────────
    print('=' * 60)
    print('  步骤 2/2 — 启动 PTP Master (ptp4l + phc2sys)')
    print('=' * 60)

    hw_ts = check_hw_timestamp(iface)
    ptp4l_proc, phc2sys_proc = start_ptp_master(config, hw_ts)

    print('\n[运行] PTP 同步已启动，按 Ctrl+C 停止')

    def _shutdown(sig, frame):
        print('\n[停止] 正在终止 PTP 进程...')
        for proc in [ptp4l_proc, phc2sys_proc]:
            if proc and proc.poll() is None:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    ptp4l_proc.wait()


if __name__ == '__main__':
    main()
