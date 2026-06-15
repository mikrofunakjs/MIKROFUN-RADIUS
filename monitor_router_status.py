#!/usr/bin/env python3
"""
Router Status Monitor
Checks WireGuard handshake + ping to determine router online/offline.
Run via systemd timer or cron every minute.
"""
import subprocess
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'web'))
from database import execute_query

def ping_ip(ip):
    try:
        r = subprocess.run(['ping', '-c', '1', '-W', '1', ip],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except:
        return False

def get_wg_peers():
    peers = {}
    try:
        result = subprocess.run(['wg', 'show'], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return peers

        current = None
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line.startswith('peer:'):
                current = line.split('peer:')[1].strip()
                peers[current] = 'offline'
            elif current and 'latest handshake:' in line:
                hs = line.split('latest handshake:')[1].strip()
                if 'year' in hs or 'day' in hs or 'hour' in hs:
                    peers[current] = 'offline'
                elif 'second' in hs:
                    peers[current] = 'online'
                elif 'minute' in hs:
                    nums = re.findall(r'\d+', hs.split(',')[0])
                    if nums and int(nums[0]) < 3:
                        peers[current] = 'online'
    except Exception as e:
        print(f"WG error: {e}")
    return peers

import time

def update():
    peers = get_wg_peers()
    # Use existing DB connection logic if possible, or new one
    routers = execute_query(
        "SELECT id, name, vpn_ip, vpn_public_key, status FROM routers", fetch=True
    )
    if not routers:
        # print("No routers found")
        return

    for r in routers:
        pub_key = r.get('vpn_public_key', '')
        vpn_ip = r.get('vpn_ip', '')
        old = r.get('status', 'offline')
        new = 'offline'

        if pub_key and pub_key in peers and peers[pub_key] == 'online':
            if vpn_ip and ping_ip(vpn_ip):
                new = 'online'

        if new != old:
            execute_query("UPDATE routers SET status=%s, last_seen=NOW() WHERE id=%s", (new, r['id']))
            print(f"[Monitor] {r.get('name','?')}: {old} -> {new}")
        # else:
        #     print(f"  {r.get('name','?')}: {new}")

def start_monitor():
    print("Starting Router Monitor Service...")
    while True:
        try:
            update()
        except Exception as e:
            print(f"Router Monitor Error: {e}")
        time.sleep(60)

if __name__ == '__main__':
    start_monitor()
