"""
WireGuard VPN Helper Functions
"""
import subprocess
import os
import requests

WG_INTERFACE = "wg0"
WG_CONF = "/etc/wireguard/wg0.conf" if os.name != 'nt' else os.path.join(os.getcwd(), 'data', 'wg0.conf')
VPN_NETWORK = "10.66.66"

# Ensure data dir exists for Windows
if os.name == 'nt' and not os.path.exists(os.path.join(os.getcwd(), 'data')):
    os.makedirs(os.path.join(os.getcwd(), 'data'))

def generate_wireguard_keys():
    if os.name == 'nt':
        import secrets, base64
        priv_key = base64.b64encode(secrets.token_bytes(32)).decode()
        pub_key = base64.b64encode(secrets.token_bytes(32)).decode()
        return priv_key, pub_key

    wg_cmd = 'wg'
    for path in ['/usr/bin/wg', '/usr/sbin/wg', '/usr/local/bin/wg']:
        if os.path.exists(path):
            wg_cmd = path
            break
            
    try:
        priv = subprocess.run([wg_cmd, 'genkey'], capture_output=True, text=True, check=True)
        priv_key = priv.stdout.strip()
        pub = subprocess.run([wg_cmd, 'pubkey'], input=priv_key, capture_output=True, text=True, check=True)
        pub_key = pub.stdout.strip()
        return priv_key, pub_key
    except Exception as e:
        print(f"Key gen error: {e}")
        return None, None

def get_server_public_key():
    try:
        if os.name == 'nt':
             return "WINDOWS_TEST_KEY"
             
        for path in ['/etc/wireguard/publickey', '/etc/wireguard/server_publickey']:
            if os.path.exists(path):
                with open(path) as f:
                    return f.read().strip()
        if os.name != 'nt':
            r = subprocess.run(['grep', 'PrivateKey', WG_CONF], capture_output=True, text=True)
            if r.returncode == 0:
                privkey = r.stdout.split('=', 1)[1].strip().split()[0] if '=' in r.stdout else ''
                if privkey:
                    pub = subprocess.run(['wg', 'pubkey'], input=privkey, capture_output=True, text=True, check=False)
                    if pub.returncode == 0:
                        return pub.stdout.strip()
        return "SERVER_KEY_NOT_FOUND"
    except Exception as e:
        return f"Error: {e}"

def get_next_vpn_ip():
    from database import execute_query
    routers = execute_query("SELECT vpn_ip FROM routers WHERE vpn_ip IS NOT NULL", fetch=True)
    used = set()
    if routers:
        for r in routers:
            if r.get('vpn_ip'):
                try:
                    used.add(int(r['vpn_ip'].split('.')[-1]))
                except:
                    pass
    for i in range(2, 255):
        if i not in used:
            return f"{VPN_NETWORK}.{i}"
    return None

def add_wireguard_peer(name, vpn_ip, public_key):
    try:
        if os.name == 'nt': return True
        if not os.path.exists(WG_CONF):
            with open(WG_CONF, 'w') as f:
                f.write(f"[Interface]\nAddress = {VPN_NETWORK}.1/24\nListenPort = 51820\nSaveConfig = false\n")
        with open(WG_CONF, 'r') as f: config = f.read()
        try:
            subprocess.run(['wg', 'set', WG_INTERFACE, 'peer', public_key, 'allowed-ips', f'{vpn_ip}/32', 'persistent-keepalive', '25'], check=True)
        except Exception as e: print(f"Kernel WG set error: {e}")
        if f"PublicKey = {public_key}" not in config:
            if "SaveConfig = true" in config:
                config = config.replace("SaveConfig = true", "SaveConfig = false")
                with open(WG_CONF, 'w') as f: f.write(config)
            peer = f"\n# {name}\n[Peer]\nPublicKey = {public_key}\nAllowedIPs = {vpn_ip}/32\nPersistentKeepalive = 25\n"
            with open(WG_CONF, 'a') as f: f.write(peer)
        return True
    except Exception as e:
        print(f"Add peer error: {e}")
        return False

def remove_wireguard_peer(public_key):
    try:
        if not os.path.exists(WG_CONF): return True
        with open(WG_CONF, 'r') as f: lines = f.readlines()
        new_lines = []
        skip = False
        for i, line in enumerate(lines):
            if f"PublicKey = {public_key}" in line:
                skip = True
                if new_lines and '[Peer]' in new_lines[-1]: new_lines.pop()
                if new_lines and new_lines[-1].strip().startswith('#'): new_lines.pop()
                continue
            if skip:
                if line.strip().startswith('[') or (line.strip().startswith('#') and i + 1 < len(lines) and '[Peer]' in lines[i + 1]): skip = False
                else: continue
            new_lines.append(line)
        with open(WG_CONF, 'w') as f: f.writelines(new_lines)
        if os.name != 'nt':
            subprocess.run(['wg', 'set', WG_INTERFACE, 'peer', public_key, 'remove'], check=False)
            subprocess.run(['systemctl', 'reload', f'wg-quick@{WG_INTERFACE}'], capture_output=True, text=True)
        return True
    except Exception as e:
        print(f"Remove peer error: {e}")
        return False

def generate_vpn_password(length=12):
    import random, string
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def update_secret_file(filepath, search_key, new_line, remove=False):
    try:
        if not os.path.exists(filepath):
            with open(filepath, 'w') as f: f.write("")
        with open(filepath, 'r') as f: lines = f.readlines()
        new_lines = []
        found = False
        for line in lines:
            if line.startswith(search_key) or f'"{search_key}"' in line or f'{search_key} ' in line:
                if not remove: new_lines.append(new_line + "\n")
                found = True
            else: new_lines.append(line)
        if not found and not remove: new_lines.append(new_line + "\n")
        with open(filepath, 'w') as f: f.writelines(new_lines)
        return True
    except Exception as e:
        print(f"Error updating {filepath}: {e}")
        return False

def add_ppp_secret(username, password, vpn_ip):
    path = '/etc/ppp/chap-secrets' if os.name != 'nt' else os.path.join(os.getcwd(), 'data', 'chap-secrets')
    new_line = f'"{username}" * "{password}" {vpn_ip}'
    update_secret_file(path, f'"{username}"', new_line)

def remove_ppp_secret(username):
    path = '/etc/ppp/chap-secrets' if os.name != 'nt' else os.path.join(os.getcwd(), 'data', 'chap-secrets')
    update_secret_file(path, f'"{username}"', "", remove=True)

def add_ipsec_secret(username, psk):
    pass
    
def remove_ipsec_secret(username):
    pass

def generate_mikrotik_script(router_name, vpn_ip, private_key, server_ip, vpn_type='wireguard', vpn_password=None):
    from web.blueprints.settings import get_setting
    rad_secret = get_setting('radius_secret', 'testing123')
    
    if vpn_type == 'l2tp':
        return f"""# L2TP script
/interface l2tp-client add name=l2tp-nas connect-to={server_ip} user="{router_name}" password="{vpn_password}" ipsec-secret="mikrofun_vpn" use-ipsec=yes use-peer-dns=no allow=mschap2 disabled=no
/ip route add distance=1 dst-address=10.66.66.1/32 gateway=l2tp-nas
/radius add address=10.66.66.1 secret={rad_secret} service=ppp,dhcp
/ppp aaa set use-radius=yes
"""
    elif vpn_type == 'sstp':
        return f"""# SSTP script
/interface sstp-client add name=sstp-nas connect-to={server_ip} user="{router_name}" password="{vpn_password}" profile=default-encryption verify-server-certificate=no disabled=no
/ip route add distance=1 dst-address=10.66.66.1/32 gateway=sstp-nas
/radius add address=10.66.66.1 secret={rad_secret} service=ppp,dhcp
"""
    elif vpn_type == 'direct_local' or vpn_type == 'public_ip':
        return f"""/radius add address={server_ip} secret={rad_secret} service=ppp,dhcp
/ppp aaa set use-radius=yes
/ip dhcp-server set [find] use-radius=yes
"""
    else:
        # WireGuard CLEAN SYNC (RouterOS v7)
        server_pub = get_server_public_key()
        return f"""# ============================================
# WireGuard Setup for {router_name} (RouterOS v7)
# ============================================

# 1. Clean Stale Config
/ip address
:local oldIP [find interface=wg-nas]
:if ([:len $oldIP] > 0) do={{ remove $oldIP }}

/radius
:local oldRad [find address=10.66.66.1]
:if ([:len $oldRad] > 0) do={{ remove $oldRad }}

/interface wireguard
:local oldWG [find name=wg-nas]
:if ([:len $oldWG] > 0) do={{ remove $oldWG }}

# 2. Add Fresh Interface (Unbound Port)
add name=wg-nas private-key="{private_key}"

# 3. Add Peer
/interface wireguard peers
add allowed-address=10.66.66.0/24 endpoint-address={server_ip} endpoint-port=51820 interface=wg-nas public-key="{server_pub}" persistent-keepalive=25s

# 4. Add IP Address
/ip address
add address={vpn_ip}/24 interface=wg-nas network=10.66.66.0

# 5. Firewall
/ip firewall filter
:if ([:len [find comment="Allow Ping from VPS" chain=input]] = 0) do={{
    add action=accept chain=input protocol=icmp in-interface=wg-nas comment="Allow Ping from VPS"
}}

# 6. RADIUS Configuration
/radius
add address=10.66.66.1 secret={rad_secret} service=ppp,dhcp

/ppp aaa
set use-radius=yes
/ip dhcp-server
set [find] use-radius=yes
/ppp profile
set *0 use-encryption=no

# 7. Verify
# /ping 10.66.66.1
"""
