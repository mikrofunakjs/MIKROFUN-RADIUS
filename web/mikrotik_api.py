import socket
import hashlib
import binascii
import sys

class MikrotikApi:
    def __init__(self, host, port=8728, timeout=10):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.connected = False

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.host, self.port))
            self.connected = True
            return True
        except Exception as e:
            print(f"API Connect Error: {e}")
            self.connected = False
            return False

    def close(self):
        if self.sock:
            self.sock.close()
            self.connected = False

    def login(self, username, password):
        if not self.connected:
            if not self.connect():
                return False

        # Try Modern Login (RouterOS v6.43+)
        # Send /login with name and password immediately
        self.send_command(['/login', '=name=' + username, '=password=' + password])
        res = self.read_response()
        
        # Check if successful (!done)
        if '!done' in res:
            # If there is a 'ret' (challenge), it means modern login failed/ignored and it wants legacy challenge
            if 'ret' in res['!done']:
                # Legacy Fallback (MD5 Challenge)
                challenge = res['!done']['ret']
                chal_bytes = binascii.unhexlify(challenge)
                md5 = hashlib.md5()
                md5.update(b'\x00')
                md5.update(password.encode('utf-8'))
                md5.update(chal_bytes)
                resp = '00' + md5.hexdigest()
                
                self.send_command(['/login', '=name=' + username, '=response=' + resp])
                res = self.read_response()
                if '!done' in res:
                    return True
            else:
                return True
        
        return False

    def send_command(self, cmd_list):
        for w in cmd_list:
            self.write_word(w)
        self.write_word('') # End of sentence

    def write_word(self, w):
        b = w.encode('utf-8')
        l = len(b)
        if l < 0x80:
            self.sock.send(bytes([l]))
        elif l < 0x4000:
            l |= 0x8000
            self.sock.send(bytes([(l >> 8) & 0xFF, l & 0xFF]))
        elif l < 0x200000:
            l |= 0xC00000
            self.sock.send(bytes([(l >> 16) & 0xFF, (l >> 8) & 0xFF, l & 0xFF]))
        else:
            l |= 0xE0000000
            self.sock.send(bytes([(l >> 24) & 0xFF, (l >> 16) & 0xFF, (l >> 8) & 0xFF, l & 0xFF]))     
        self.sock.send(b)

    def read_word(self):
        b = self.sock.recv(1)
        if not b: return None
        l = b[0]
        if (l & 0x80) == 0:
            pass
        elif (l & 0xC0) == 0x80:
            l &= ~0x80
            b2 = self.sock.recv(1)
            l = (l << 8) | b2[0]
        elif (l & 0xE0) == 0xC0:
            l &= ~0xC0
            b2 = self.sock.recv(2)
            l = (l << 8) | b2[0]
            l = (l << 8) | b2[1]
        elif (l & 0xF0) == 0xE0:
            l &= ~0xE0
            b2 = self.sock.recv(3)
            l = (l << 8) | b2[0]
            l = (l << 8) | b2[1]
            l = (l << 8) | b2[2]
        elif (l & 0xF8) == 0xF0:
            l = self.sock.recv(1)[0]
            l = (l << 8) | self.sock.recv(1)[0]
            l = (l << 8) | self.sock.recv(1)[0]
            l = (l << 8) | self.sock.recv(1)[0]
        
        ret = b''
        while len(ret) < l:
            conn = self.sock.recv(l - len(ret))
            if not conn: break
            ret += conn
        return ret.decode('utf-8', errors='ignore')

    def read_response(self):
        res = {}
        while True:
            w = self.read_word()
            if w is None: break
            if w == '': continue
            
            if w.startswith('!'):
                line = w
                attrs = {}
                while True:
                    w2 = self.read_word()
                    if w2 == '': 
                        break
                    if '=' in w2:
                        parts = w2.split('=', 2)
                        if len(parts) == 3:
                            attrs[parts[1]] = parts[2]
                res[line] = attrs
                if line == '!done' or line == '!trap' or line == '!fatal':
                    break
        return res

    def query(self, cmd_list):
        self.send_command(cmd_list)
        rows = []
        while True:
            w = self.read_word()
            if w is None: break
            if w == '': continue
            
            if w == '!re':
                row = {}
                while True:
                    w2 = self.read_word()
                    if w2 == '': break
                    if '=' in w2:
                        parts = w2.split('=', 2)
                        if len(parts) == 3:
                            row[parts[1]] = parts[2]
                rows.append(row)
            elif w == '!done':
                # Drain
                while True:
                   if self.read_word() == '': break
                break
            elif w == '!trap' or w == '!fatal':
                # Drain
                while True:
                   if self.read_word() == '': break
                return None
        return rows

    def kick_user(self, username):
        """Finds and removes active PPP user"""
        try:
            # 1. Find ID
            active_users = self.query(['/ppp/active/print', '?name=' + username, '=.proplist=.id'])
            if active_users is None:
                 return False, "API Error (Trap received)"
                 
            if not active_users:
                return True, "User already offline" # Considered success
            
            # 2. Remove each ID found
            for user in active_users:
                pk = user.get('.id')
                if pk:
                    self.send_command(['/ppp/active/remove', '=.id=' + pk])
                    self.read_response() # Clear buffer
            
            return True, "User kicked via API"
        except Exception as e:
            return False, str(e)

    def kick_hotspot_user(self, username, mac_address=None):
        """Finds and removes active Hotspot user"""
        try:
            active_users = self.query(['/ip/hotspot/active/print', '?user=' + username, '=.proplist=.id'])
            
            # Hotspot login via MAC Auth / MAC Cookie sets 'user' as the MAC Address
            if not active_users and mac_address:
                active_users = self.query(['/ip/hotspot/active/print', '?user=' + mac_address, '=.proplist=.id'])

            if active_users is None:
                 return False, "API Error (Trap received)"
                 
            if not active_users:
                return True, "User already offline"
            
            for user in active_users:
                pk = user.get('.id')
                if pk:
                    self.send_command(['/ip/hotspot/active/remove', '=.id=' + pk])
                    self.read_response()
            
            return True, "Hotspot User kicked via API"
        except Exception as e:
            return False, str(e)

    def get_active_user(self, username):
        """Check if user is currently active"""
        try:
            # simple print where name=username
            rows = self.query(['/ppp/active/print', '?name=' + username])
            if rows and len(rows) > 0:
                return rows[0]
            # Also check hotspot
            rows = self.query(['/ip/hotspot/active/print', '?user=' + username])
            if rows and len(rows) > 0:
                return rows[0]
            return None
        except Exception as e:
            print(f"API get_active_user Error: {e}")
            return None

    def get_all_active_sessions(self):
        """Fetch all active sessions (PPPoE & Hotspot) from the router"""
        sessions = []
        try:
            # 1. Fetch PPP Active
            ppp = self.query(['/ppp/active/print'])
            for p in ppp or []:
                sessions.append({
                    'username': p.get('name'),
                    'session_id': p.get('.id'),
                    'caller_id': p.get('caller-id'),
                    'address': p.get('address'),
                    'type': 'ppp'
                })
            # 2. Fetch Hotspot Active
            hotspot = self.query(['/ip/hotspot/active/print'])
            for h in hotspot or []:
                sessions.append({
                    'username': h.get('user'),
                    'session_id': h.get('.id'),
                    'caller_id': h.get('mac-address'),
                    'address': h.get('address'),
                    'type': 'hotspot'
                })
            return sessions
        except Exception as e:
            print(f"API get_all_active_sessions Error: {e}")
            return []

    def trace_mac_by_ip(self, ip_address):
        """Finds a MAC address for a given IP among hotspot hosts"""
        try:
            # Look into hotspot hosts list which is the most active
            res = self.query(['/ip/hotspot/host/print', f'?address={ip_address}', '=.proplist=mac-address'])
            if res and len(res) > 0:
                return res[0].get('mac-address')
            
            # Fallback to ARP list if not found in hotspot
            res = self.query(['/ip/arp/print', f'?address={ip_address}', '=.proplist=mac-address'])
            if res and len(res) > 0:
                return res[0].get('mac-address')
                
            return None
        except Exception as e:
            print(f"API trace_mac_by_ip Error: {e}")
            return None

    def api_hotspot_login(self, username, password, mac, ip):
        """Force login a hotspot user via API (Innovative Method)"""
        try:
            # We add user directly to active list
            # Note: This requires the user to exist in local or radius
            # For Radius, it's safer to use the 'login' command if available 
            # but 'active add' is more universal in API.
            cmd = [
                '/ip/hotspot/active/add', 
                f'=user={username}', 
                f'=password={password}', 
                f'=mac-address={mac}', 
                f'=address={ip}'
            ]
            self.send_command(cmd)
            res = self.read_response()
            return True, "Login Success via API"
        except Exception as e:
            return False, str(e)

    def add_firewall_address_list(self, list_name, address, comment=""):
        """Adds an IP or subnet to the MikroTik firewall address-list"""
        try:
            cmd = ['/ip/firewall/address-list/add', f'=list={list_name}', f'=address={address}']
            if comment:
                cmd.append(f'=comment={comment}')
            
            self.send_command(cmd)
            # Check response pattern
            # If successful, returns word: !done  word: =ret=*xx
            word = self.read_word()
            
            if word == '!trap' or word == '!fatal':
                resp = []
                while True:
                    w = self.read_word()
                    if w == '': break
                    resp.append(w)
                # Parse trap message
                message = "API Error"
                for r in resp:
                    if r.startswith('=message='):
                        message = r.split('=', 2)[2]
                        break
                return False, message
                
            # Read until done
            while True:
                w = self.read_word()
                if w == '': break
            return True, "Success"
            
        except Exception as e:
            return False, str(e)

    def sync_walled_garden(self, domains):
        """Adds a list of domains to Hotspot Walled Garden IP (HTTPS Support) + DNS Bypass"""
        try:
            # 1. Fetch existing from IP based walled garden to avoid duplicates
            existing = self.query(['/ip/hotspot/walled-garden/ip/print', '=.proplist=dst-host,dst-port,protocol,comment'])
            existing_domains = []
            has_dns_bypass = False
            if existing:
                existing_domains = [item.get('dst-host') for item in existing if item.get('dst-host')]
                # Check if DNS bypass already exists
                for item in existing:
                    if item.get('dst-port') == '53' and item.get('comment', '').startswith('MikroFun'):
                        has_dns_bypass = True
                        break

            success_count = 0

            # 2. Add DNS bypass rules (essential for domain resolution)
            if not has_dns_bypass:
                for proto in ['udp', 'tcp']:
                    cmd = ['/ip/hotspot/walled-garden/ip/add',
                           f'=protocol={proto}', '=dst-port=53',
                           '=action=accept', '=comment=MikroFun DNS Bypass']
                    self.send_command(cmd)
                    while True:
                        w = self.read_word()
                        if w is None or w == '': break
                    success_count += 1

            # 3. Add domain entries
            for domain in domains:
                if domain not in existing_domains:
                    cmd = ['/ip/hotspot/walled-garden/ip/add', f'=dst-host={domain}', '=action=accept', '=comment=MikroFun Gateway Bypass']
                    self.send_command(cmd)
                    
                    trap = False
                    while True:
                        w = self.read_word()
                        if w is None or w == '': break
                        if w == '!trap' or w == '!fatal': trap = True
                    if not trap:
                        success_count += 1
                        
            return True, f"Synced {success_count} rules (DNS + domains) to Walled Garden IP"
        except Exception as e:
            return False, f"Failed to sync Walled Garden: {str(e)}"

    def sync_hotspot_profile(self, profile_name, rate_limit=None, shared_users=1, pool_name=None):
        """Create or update MikroTik Hotspot User Profile (for RADIUS voucher)"""
        try:
            if not self.login(self.username, self.password):
                return False, "Login failed"
            
            # Check if profile already exists
            existing = self.query(['/ip/hotspot/user/profile/print', f'?name={profile_name}'])
            
            if existing:
                # Update existing
                cmd = ['/ip/hotspot/user/profile/set', f'=numbers={profile_name}']
            else:
                # Create new
                cmd = ['/ip/hotspot/user/profile/add', f'=name={profile_name}']
            
            if rate_limit:
                cmd.append(f'=rate-limit={rate_limit}')
            if shared_users and int(shared_users) > 0:
                cmd.append(f'=shared-users={shared_users}')
            if pool_name:
                cmd.append(f'=address-pool={pool_name}')
            
            self.send_command(cmd)
            
            trap = False
            while True:
                w = self.read_word()
                if w is None or w == '': break
                if w == '!trap' or w == '!fatal': trap = True
            
            if trap:
                return False, f"Failed to sync profile: {profile_name}"
            return True, f"Profile '{profile_name}' synced to MikroTik"
        except Exception as e:
            return False, f"Sync error: {str(e)}"

