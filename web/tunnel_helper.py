"""
MikroTunnel Helper - VPN NAT Traversal for Remote Mikrotik Access
Manages L2TP tunnel creation, iptables port forwarding, and MikroTik script generation.
"""
import subprocess
import os
import random
import string
from web.database import execute_query

# Tunnel Network Configuration
TUNNEL_NETWORK = "10.10.10"   # Internal VPN subnet
TUNNEL_PORT_MIN = 10001       # Minimum public port
TUNNEL_PORT_MAX = 19999       # Maximum public port

# L2TP Config Paths (Linux VPS)
CHAP_SECRETS = "/etc/ppp/chap-secrets"
IPSEC_SECRETS = "/etc/ipsec.secrets"


def _run_cmd(cmd, check=False):
    """Run a shell command safely. Returns (success, output)."""
    try:
        if os.name == 'nt':
            # Windows dev mode - simulate
            return True, "simulated"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        if check and result.returncode != 0:
            return False, result.stderr.strip()
        return True, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def ensure_system_config():
    """Ensure IP forwarding is enabled and MSS clamping is active."""
    if os.name == 'nt':
        return True
    
    # Enable IPv4 Forwarding
    _run_cmd("sysctl -w net.ipv4.ip_forward=1")
    
    # MSS Clamping (MTU Fix for L2TP)
    # We use -I to ensure it is at the top of the FORWARD chain
    # Check if rule already exists to avoid duplicates
    exists, _ = _run_cmd("iptables -C FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu")
    if not exists:
        _run_cmd("iptables -I FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu")
    
    return True


def get_next_tunnel_ip():
    """Allocate the next available 10.10.10.x IP for a tunnel."""
    used = execute_query(
        "SELECT internal_ip FROM tunnels WHERE internal_ip IS NOT NULL",
        fetch=True
    ) or []
    used_ips = {r['internal_ip'] for r in used}
    
    # Also exclude .1 (server gateway) and .0/.255
    for i in range(2, 254):
        ip = f"{TUNNEL_NETWORK}.{i}"
        if ip not in used_ips:
            return ip
    return None


def get_available_ports():
    """Find 3 consecutive unused ports in the tunnel port range."""
    used = execute_query(
        "SELECT public_winbox_port, public_web_port, public_api_port FROM tunnels",
        fetch=True
    ) or []
    used_ports = set()
    for r in used:
        if r.get('public_winbox_port'):
            used_ports.add(r['public_winbox_port'])
        if r.get('public_web_port'):
            used_ports.add(r['public_web_port'])
        if r.get('public_api_port'):
            used_ports.add(r['public_api_port'])
    
    # Find 3 consecutive available ports
    for p in range(TUNNEL_PORT_MIN, TUNNEL_PORT_MAX - 2, 3):
        if p not in used_ports and (p + 1) not in used_ports and (p + 2) not in used_ports:
            return p, p + 1, p + 2
    return None, None, None


def generate_tunnel_password(length=12):
    """Generate a random password for VPN authentication."""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def generate_tunnel_username(router_name):
    """Generate a VPN username based on router name."""
    safe = ''.join(c if c.isalnum() else '_' for c in router_name.lower())
    suffix = ''.join(random.choices(string.digits, k=4))
    return f"tun_{safe}_{suffix}"


# ─── IPTABLES NAT Management ──────────────────────────────

def add_iptables_nat(public_port, internal_ip, internal_port):
    """Add iptables DNAT rule: public_port → internal_ip:internal_port"""
    # 0. UFW Compatibility: Allow the public port
    _run_cmd(f"ufw allow {public_port}/tcp 2>/dev/null")

    # 1. PREROUTING for incoming traffic
    cmd_pre = (
        f"iptables -t nat -A PREROUTING -p tcp --dport {public_port} "
        f"-j DNAT --to-destination {internal_ip}:{internal_port}"
    )
    # 2. FORWARD to allow the traffic
    # We use -I (Insert) to place it before any DROP rules
    cmd_fwd = (
        f"iptables -I FORWARD -p tcp -d {internal_ip} --dport {internal_port} "
        f"-j ACCEPT"
    )
    # 3. POSTROUTING to ensure Mikrotik replies via the tunnel
    cmd_post = (
        f"iptables -t nat -A POSTROUTING -d {internal_ip} -p tcp --dport {internal_port} "
        f"-j MASQUERADE"
    )
    ok1, _ = _run_cmd(cmd_pre)
    ok2, _ = _run_cmd(cmd_fwd)
    ok3, _ = _run_cmd(cmd_post)
    return ok1 and ok2 and ok3


def remove_iptables_nat(public_port, internal_ip, internal_port):
    """Remove specific iptables DNAT rule."""
    cmd_pre = (
        f"iptables -t nat -D PREROUTING -p tcp --dport {public_port} "
        f"-j DNAT --to-destination {internal_ip}:{internal_port}"
    )
    cmd_fwd = (
        f"iptables -D FORWARD -p tcp -d {internal_ip} --dport {internal_port} "
        f"-j ACCEPT"
    )
    cmd_post = (
        f"iptables -t nat -D POSTROUTING -d {internal_ip} -p tcp --dport {internal_port} "
        f"-j MASQUERADE"
    )
    _run_cmd(cmd_pre)
    _run_cmd(cmd_fwd)
    _run_cmd(cmd_post)


def setup_tunnel_nat(internal_ip, winbox_port, web_port, api_port, mk_winbox_port=8291, mk_web_port=80, mk_api_port=8728):
    """Setup full NAT for a tunnel: public port → MikroTik actual port."""
    ensure_system_config()
    ok1 = add_iptables_nat(winbox_port, internal_ip, mk_winbox_port)
    ok2 = add_iptables_nat(web_port, internal_ip, mk_web_port)
    ok3 = add_iptables_nat(api_port, internal_ip, mk_api_port)
    return ok1 and ok2 and ok3


def teardown_tunnel_nat(internal_ip, winbox_port, web_port, api_port, mk_winbox_port=8291, mk_web_port=80, mk_api_port=8728):
    """Remove all NAT rules for a tunnel."""
    remove_iptables_nat(winbox_port, internal_ip, mk_winbox_port)
    remove_iptables_nat(web_port, internal_ip, mk_web_port)
    remove_iptables_nat(api_port, internal_ip, mk_api_port)


def save_iptables():
    """Persist iptables rules so they survive reboot."""
    _run_cmd("netfilter-persistent save 2>/dev/null || iptables-save > /etc/iptables.rules")


# ─── L2TP/IPsec Secret Management ──────────────────────────

def add_tunnel_l2tp_secret(username, password, internal_ip):
    """Add L2TP user to chap-secrets and ipsec.secrets."""
    if os.name == 'nt':
        print(f"[SIM] Add L2TP secret: {username} → {internal_ip}")
        return True
    
    # chap-secrets format: username * password ip
    chap_line = f'{username}\t*\t{password}\t{internal_ip}\n'
    try:
        with open(CHAP_SECRETS, 'a') as f:
            f.write(chap_line)
    except Exception as e:
        print(f"Error writing chap-secrets: {e}")
        return False
    
    # ipsec.secrets format: username : EAP "password"
    # ipsec_line = f'{username} : EAP "{password}"\n'
    # try:
    #     with open(IPSEC_SECRETS, 'a') as f:
    #         f.write(ipsec_line)
    #     print(f"Error writing ipsec.secrets: {e}")
    #     return False
    
    # No need to restart xl2tpd, pppd detects chap-secrets changes automatically
    return True


def remove_tunnel_l2tp_secret(username):
    """Remove L2TP user from chap-secrets and ipsec.secrets."""
    if os.name == 'nt':
        print(f"[SIM] Remove L2TP secret: {username}")
        return True
    
    for filepath in [CHAP_SECRETS]: # IPSEC_SECRETS not needed for L2TP
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()
            with open(filepath, 'w') as f:
                for line in lines:
                    if username not in line:
                        f.write(line)
        except Exception as e:
            print(f"Error modifying {filepath}: {e}")
    
    # No need to restart xl2tpd, pppd detects chap-secrets changes automatically
    return True


# ─── Connectivity Check ──────────────────────────────────

def check_tunnel_alive(internal_ip):
    """Ping check to see if tunnel is connected."""
    if os.name == 'nt':
        return False  # Can't ping tunnel from Windows dev
    ok, output = _run_cmd(f"ping -c 1 -W 2 {internal_ip}")
    return ok and "1 received" in output


# ─── MikroTik Script Generation ──────────────────────────

def get_server_public_ip():
    """Get the public IP of this VPS."""
    try:
        import requests
        return requests.get('https://api.ipify.org', timeout=3).text.strip()
    except:
        return "YOUR_SERVER_IP"


def generate_mikrotik_tunnel_script(server_ip, username, password, ipsec_secret="mikrofun_vpn"):
    """Generate MikroTik script for L2TP client connection to this VPS."""
    return f"""# ============================================
# MikroTunnel - Remote Access Setup Script
# Server: {server_ip}
# User: {username}
# ============================================
# Paste script ini di New Terminal Winbox
# ============================================

# 1. Buat L2TP Client Interface
/interface l2tp-client add \\
    name=mikrotunnel \\
    connect-to={server_ip} \\
    user={username} \\
    password={password} \\
    use-ipsec=yes \\
    ipsec-secret={ipsec_secret} \\
    allow=mschap2 \\
    disabled=no \\
    add-default-route=no \\
    profile=default

# 2. Pastikan koneksi auto-reconnect
/interface l2tp-client set mikrotunnel keepalive-timeout=30

# 3. Verifikasi
:delay 5s
/interface l2tp-client print where name=mikrotunnel

# ============================================
# Done! Router akan otomatis konek ke VPS.
# Admin bisa remote via:
#   Winbox : {server_ip}:<PORT_WINBOX>
#   Web    : {server_ip}:<PORT_WEB>
#   API    : {server_ip}:<PORT_API>
# ============================================
"""
