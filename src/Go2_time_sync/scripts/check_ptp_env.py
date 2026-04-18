#!/usr/bin/env python3
"""
检查 PTP 同步环境的辅助脚本
用法: python3 scripts/check_ptp_env.py [--config config/ptp_sync.yaml]
"""

import argparse
import os
import socket
import subprocess
import sys

import yaml


def run(cmd: list) -> tuple:
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def check_tool(name: str) -> bool:
    code, _, _ = run(['which', name])
    ok = code == 0
    print(f'  {"[OK]" if ok else "[缺失]"} {name}')
    return ok


def check_interface(iface: str):
    print(f'\n[网卡检查] {iface}')
    code, out, err = run(['ip', 'link', 'show', iface])
    if code != 0:
        print(f'  [错误] 网卡 {iface} 不存在: {err.strip()}')
        return

    if 'UP' in out:
        print(f'  [OK] 网卡已启动')
    else:
        print(f'  [警告] 网卡未启动，请执行: sudo ip link set {iface} up')

    # 检查 IP
    code2, out2, _ = run(['ip', 'addr', 'show', iface])
    if 'inet ' in out2:
        for line in out2.splitlines():
            if 'inet ' in line:
                print(f'  [OK] IP: {line.strip()}')
    else:
        print(f'  [警告] 网卡无 IP 地址')

    # 检查硬件时间戳
    code3, out3, _ = run(['ethtool', '-T', iface])
    if code3 == 0:
        if 'hardware-transmit' in out3.lower():
            print(f'  [OK] 支持硬件时间戳')
        else:
            print(f'  [警告] 不支持硬件时间戳（将使用软件时间戳）')
    else:
        print(f'  [警告] 无法查询时间戳能力（ethtool 未安装或权限不足）')


def check_ntp_servers(servers: list[str], timeout: int = 5):
    print(f'\n[NTP 服务器连通性]')
    if not servers:
        print('  [警告] 服务器列表为空')
        return
    any_ok = False
    for server in servers:
        try:
            # 仅测试 DNS + TCP 端口可达性（不实际发送 NTP 包）
            sock = socket.create_connection((server, 123), timeout=timeout)
            sock.close()
            print(f'  [OK] {server} 可达')
            any_ok = True
        except (socket.timeout, socket.gaierror, OSError) as e:
            print(f'  [警告] {server} 不可达: {e}')
    if not any_ok:
        print('  [警告] 所有 NTP 服务器均不可达，NTP 校准将会失败（网络新时变时间可能偏差较大）')


def check_lidar_reachable(ip: str):
    print(f'\n[雷达连通性] {ip}')
    code, _, _ = run(['ping', '-c', '3', '-W', '1', ip])
    if code == 0:
        print(f'  [OK] 雷达 {ip} 可达')
    else:
        print(f'  [警告] 无法 ping 通 {ip}，请检查网络连接和 IP 配置')


def main():
    parser = argparse.ArgumentParser(description='PTP 环境检查')
    default_cfg = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'config', 'ptp_sync.yaml'
    )
    parser.add_argument('--config', default=default_cfg)
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    iface = config['network']['interface']
    lidar_ip = config['lidar']['ip']

    print('=== PTP 同步环境检查 ===')
    print(f'配置文件: {args.config}')
    print(f'网卡: {iface}  雷达IP: {lidar_ip}')

    print('\n[依赖工具]')
    all_ok = all([
        check_tool('ptp4l'),
        check_tool('phc2sys'),
        check_tool('ethtool'),
    ])

    check_interface(iface)

    # 检查 NTP 服务器连通性
    ntp_cfg = config.get('ntp', {})
    ntp_servers = ntp_cfg.get('servers', [
        'ntp.aliyun.com', 'cn.pool.ntp.org', 'pool.ntp.org'
    ])
    ntp_timeout = int(ntp_cfg.get('timeout', 5))
    check_ntp_servers(ntp_servers, timeout=ntp_timeout)

    check_lidar_reachable(lidar_ip)

    print('\n=== 检查完成 ===')
    if not all_ok:
        print('请先安装缺失工具: sudo apt install linuxptp ethtool')
        sys.exit(1)


if __name__ == '__main__':
    main()
