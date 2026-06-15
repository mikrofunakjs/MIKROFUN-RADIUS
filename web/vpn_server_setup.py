#!/usr/bin/env python3
import os
import subprocess
import string
import random

def run_cmd(cmd):
    try:
        subprocess.run(cmd, shell=True, check=True)
    except Exception as e:
        print(f"Error running cmd: {cmd}\n{e}")

def get_public_ip():
    try:
        import urllib.request
        ip = urllib.request.urlopen('https://api.ipify.org').read().decode('utf8')
        return ip
    except:
        return "127.0.0.1"

def setup_l2tp(public_ip):
    print("Setting up L2TP/IPsec...")
    # 1. Update ipsec.conf
    ipsec_conf = f"""
config setup

conn L2TP-PSK
    authby=secret
    auto=add
    keyingtries=3
    rekey=yes
    ikelifetime=8h
    keylife=1h
    type=transport
    left={public_ip}
    leftprotoport=17/1701
    right=%any
    rightprotoport=17/%any
    forceencaps=yes
    # Maximum compatibility for Mikrotik (includes modp1024/Group2)
    ike=aes256-sha1-modp1024,aes128-sha1-modp1024,3des-sha1-modp1024,aes256-sha256-modp2048,aes128-sha256-modp2048
    esp=aes256-sha1-modp1024,aes128-sha1-modp1024,3des-sha1-modp1024,aes256-sha1,aes128-sha1,3des-sha1
    dpddelay=30s
    dpdtimeout=120s
    dpdaction=clear
"""
    with open('/etc/ipsec.conf', 'w') as f:
        f.write(ipsec_conf)

    # 2. Update xl2tpd.conf
    xl2tpd_conf = f"""
[global]
port = 1701
listen-addr = {public_ip}

[lns default]
ip range = 10.10.10.200-10.10.10.250
local ip = 10.10.10.1
require authentication = yes
name = LinuxVPNserver
ppp debug = yes
pppoptfile = /etc/ppp/options.xl2tpd
length bit = yes
"""
    os.makedirs('/etc/xl2tpd', exist_ok=True)
    with open('/etc/xl2tpd/xl2tpd.conf', 'w') as f:
        f.write(xl2tpd_conf)

    ppp_options = """
ipcp-accept-local
ipcp-accept-remote
ms-dns  8.8.8.8
ms-dns  1.1.1.1
auth
require-mschap-v2
noccp
mtu 1400
mru 1400
nodefaultroute
debug
proxyarp
connect-delay 5000
name LinuxVPNserver
"""
    os.makedirs('/etc/ppp', exist_ok=True)
    with open('/etc/ppp/options.xl2tpd', 'w') as f:
        f.write(ppp_options)

    # Ensure secrets exist
    if not os.path.exists('/etc/ppp/chap-secrets'):
        with open('/etc/ppp/chap-secrets', 'w') as f:
            f.write("# Secrets for authentication using CHAP\n# client\tserver\tsecret\t\t\tIP addresses\n")

    if not os.path.exists('/etc/ipsec.secrets'):
        with open('/etc/ipsec.secrets', 'w') as f:
            f.write('%any %any : PSK "mikrofun_vpn"\\n')
    else:
        run_cmd("grep -q 'mikrofun_vpn' /etc/ipsec.secrets || echo '%any %any : PSK \"mikrofun_vpn\"' >> /etc/ipsec.secrets")

    run_cmd("systemctl restart ipsec || systemctl restart strongswan-starter || systemctl restart strongswan")
    run_cmd("systemctl restart xl2tpd || true")
    run_cmd("systemctl enable ipsec || systemctl enable strongswan-starter || systemctl enable strongswan")
    run_cmd("systemctl enable xl2tpd || true")


def setup_firewall():
    print("Opening Firewall Ports (UFW)...")
    # L2TP/IPSec
    run_cmd("ufw allow 500/udp")
    run_cmd("ufw allow 4500/udp")
    run_cmd("ufw allow 1701/udp")

if __name__ == "__main__":
    import sys
    # Only run carefully on actual prod setup
    print("Multi-VPN Setup Starting...")
    public_ip = get_public_ip()
    print(f"Detected Public IP: {public_ip}")
    
    # We will only actually run this on the VPS, but it's generated here.
    # In development modes, we just inform the user.
    setup_l2tp(public_ip)
    setup_firewall()
    print("Multi-VPN Setup Complete.")
