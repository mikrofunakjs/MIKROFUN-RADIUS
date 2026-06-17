#!/usr/bin/env python3
"""
MikroFun RADIUS Server (Python)
Authenticates PPPoE/Hotspot users against MySQL database.
Supports PAP authentication.
Configure Mikrotik: /ppp profile set default use-radius=yes
                    /ppp aaa set use-radius=yes
"""
import sys
import os
import logging
import socket
import struct
import hashlib
import threading
import mysql.connector
import datetime

import sys
import os

# --- Path auto-detection ---
# Make sure we can always import from 'web' regardless of where we start from
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from web.config import DB_CONFIG, RADIUS_SECRET as DEFAULT_SECRET, RADIUS_LOG_PATH
    DB_HOST = DB_CONFIG['host']
    DB_USER = DB_CONFIG['user']
    DB_PASS = DB_CONFIG['password']
    DB_NAME = DB_CONFIG['database']
    CONFIG_STATUS = "SUCCESS: Using web.config"
except Exception as e:
    # Fallback or development defaults
    DB_HOST = 'localhost'
    DB_USER = 'radius'
    DB_PASS = 'radiuspass123'
    DB_NAME = 'radius_db'
    DEFAULT_SECRET = 'testing123'
    RADIUS_LOG_PATH = 'radius.log'
    CONFIG_STATUS = f"WARNING: Falling back to defaults ({e})"

AUTH_PORT = 1812
ACCT_PORT = 1813

_cached_secret = None
_last_secret_update = 0

def get_secret():
    """Fetch RADIUS secret from DB with basic caching"""
    global _cached_secret, _last_secret_update
    import time
    
    # Cache for 60 seconds
    if _cached_secret and (time.time() - _last_secret_update < 60):
        return _cached_secret
        
    try:
        conn = mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT setting_value FROM settings WHERE setting_key='radius_secret'")
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            _cached_secret = row[0].strip().encode('utf-8')
            _last_secret_update = time.time()
            return _cached_secret
    except:
        pass
        
    secret_raw = DEFAULT_SECRET if isinstance(DEFAULT_SECRET, bytes) else str(DEFAULT_SECRET).encode('utf-8')
    return secret_raw.strip()

# ─── LOGGING ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(RADIUS_LOG_PATH),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger('radius')

# ─── RADIUS PROTOCOL CONSTANTS ───────────────────────────────────
CODE_ACCESS_REQUEST    = 1
CODE_ACCESS_ACCEPT     = 2
CODE_ACCESS_REJECT     = 3
CODE_ACCT_REQUEST      = 4
CODE_ACCT_RESPONSE     = 5

ATTR_USER_NAME         = 1
ATTR_USER_PASSWORD     = 2
ATTR_NAS_IP            = 4
ATTR_NAS_PORT          = 5
ATTR_SERVICE_TYPE      = 6
ATTR_FRAMED_PROTOCOL   = 7
ATTR_FRAMED_IP         = 8
ATTR_REPLY_MESSAGE     = 18
ATTR_CALLING_STATION   = 31
ATTR_ACCT_STATUS       = 40
ATTR_ACCT_SESSION_ID   = 44
ATTR_FRAMED_POOL       = 88
ATTR_VENDOR_SPECIFIC   = 26
ATTR_MESSAGE_AUTH      = 80  # CRITICAL for Mikrotik PPPoE

MIKROTIK_VENDOR_ID      = 14988
MIKROTIK_RATE_LIMIT_TYPE = 8
MIKROTIK_XMIT_LIMIT      = 17 # Upload (Router perspect, so Download for User)
MIKROTIK_RECV_LIMIT      = 16 # Download (Router perspect, so Upload for User)
MIKROTIK_TOTAL_LIMIT      = 15 # NOT Standard Mikrotik, but some versions use it. 17 is safer.

from mysql.connector import pooling

# --- DATABASE POOLING (SAT-SET) ---
_DB_POOL = None

def get_db():
    global _DB_POOL
    try:
        if _DB_POOL is None:
            _DB_POOL = pooling.MySQLConnectionPool(
                pool_name="radius_pool",
                pool_size=5, 
                pool_reset_session=True,
                host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME
            )
        return _DB_POOL.get_connection()
    except Exception as e:
        log.error(f"DB connect error (Pooling): {e}")
        # Fallback to direct connection if pool fails
        try:
            return mysql.connector.connect(
                host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME
            )
        except:
            return None

def find_customer(username):
    """Find active customer by username"""
    conn = get_db()
    if not conn:
        return None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT c.*, p.rate_limit, p.burst_limit, p.burst_threshold, p.burst_time, p.limit_at, p.pool_name, p.quota_limit, p.shared_users "
            "FROM customers c "
            "LEFT JOIN profiles p ON c.profile_id = p.id "
            "WHERE c.username = %s AND c.status = 'active'",
            (username,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row
    except Exception as e:
        log.error(f"find_customer error: {e}")
        if conn:
            conn.close()
        return None

def find_customer_by_mac(mac_address):
    """Find active customer by MAC Address"""
    conn = get_db()
    if not conn:
        return None
    try:
        cur = conn.cursor(dictionary=True)
        # Normalize MAC (remove colons and dashes)
        clean_mac = mac_address.replace(':', '').replace('-', '').upper()
        cur.execute(
            "SELECT c.*, p.rate_limit, p.burst_limit, p.burst_threshold, p.burst_time, p.limit_at, p.pool_name, p.quota_limit, p.shared_users "
            "FROM customers c "
            "LEFT JOIN profiles p ON c.profile_id = p.id "
            "WHERE REPLACE(REPLACE(UPPER(c.mac_address), ':', ''), '-', '') = %s AND c.status = 'active' "
            "LIMIT 1",
            (clean_mac,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row
    except Exception as e:
        log.error(f"find_customer_by_mac error: {e}")
        if conn:
            conn.close()
        return None

def find_voucher(code):
    """Find valid voucher by code"""
    conn = get_db()
    if not conn:
        return None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT v.*, p.rate_limit, p.burst_limit, p.burst_threshold, p.burst_time, p.limit_at, p.pool_name, p.quota_limit as p_quota_limit, p.shared_users "
            "FROM vouchers v "
            "LEFT JOIN profiles p ON v.profile_id = p.id "
            "WHERE v.code = %s AND v.status IN ('unused','active')",
            (code,)
        )
        row = cur.fetchone()
        if not row:
            log.warning(f"Voucher code '{code}' NOT FOUND in database or already expired.")
        cur.close()
        conn.close()
        return row
    except Exception as e:
        log.error(f"find_voucher database error for '{code}': {e}")
        if conn:
            conn.close()
        return None

def activate_voucher(code, duration_hours=24):
    """Mark voucher as active and set expiry"""
    conn = get_db()
    if not conn:
        return
    try:
        # Calculate expiry
        # MySQL DATE_ADD is standard
        cur = conn.cursor()
        cur.execute(
            "UPDATE vouchers SET status='active', activated_at=NOW(), "
            "expires_at=DATE_ADD(NOW(), INTERVAL %s HOUR) "
            "WHERE code=%s AND status='unused'",
            (duration_hours, code)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.error(f"activate_voucher error: {e}")
        if conn:
            conn.close()

ATTR_SESSION_TIMEOUT = 27

# ... (Previous code)


# ─── RADIUS PACKET HELPERS ───────────────────────────────────────
def parse_attrs(data):
    """Parse RADIUS attribute list from raw bytes"""
    attrs = {}
    i = 0
    while i + 2 <= len(data):
        atype = data[i]
        alen = data[i + 1]
        if alen < 2 or i + alen > len(data):
            break
        aval = data[i + 2:i + alen]
        attrs[atype] = aval
        i += alen
    return attrs

def decode_pap_password(encrypted, authenticator, secret):
    """Decode PAP User-Password"""
    pwd = b''
    prev = authenticator
    for i in range(0, len(encrypted), 16):
        block = encrypted[i:i + 16]
        h = hashlib.md5(secret + prev).digest()
        pwd += bytes(a ^ b for a, b in zip(block, h))
        prev = block
    return pwd.rstrip(b'\x00').decode('utf-8', errors='ignore')

def make_response(code, pkt_id, request_auth, secret, reply_attrs=None):
    """Build RADIUS response packet"""
    attr_bytes = b''
    if reply_attrs:
        for atype, aval in reply_attrs:
            if isinstance(aval, str):
                aval = aval.encode('utf-8')
            elif isinstance(aval, int):
                aval = struct.pack('!I', aval)
            attr_bytes += struct.pack('BB', atype, len(aval) + 2) + aval

    length = 20 + len(attr_bytes)
    # Build packet with request authenticator first (for hash calculation)
    pkt = struct.pack('!BBH', code, pkt_id, length) + request_auth + attr_bytes
    # Calculate Response Authenticator
    resp_auth = hashlib.md5(pkt[:4] + request_auth + pkt[20:] + secret).digest()
    return pkt[:4] + resp_auth + pkt[20:]

def make_vsa_mikrotik(attr_type, value):
    """Build Mikrotik Vendor-Specific Attribute"""
    if isinstance(value, str):
        value = value.encode('utf-8')
    # VSA inner: type(1) + length(1) + value
    vsa_inner = struct.pack('BB', attr_type, len(value) + 2) + value
    # VSA outer: vendor_id(4) + vsa_inner
    vsa_data = struct.pack('!I', MIKROTIK_VENDOR_ID) + vsa_inner
    # Attribute 26: type(1) + total_length(1) + vsa_data
    return struct.pack('BB', ATTR_VENDOR_SPECIFIC, len(vsa_data) + 2) + vsa_data

def check_simultaneous_use(username, limit, current_mac=None):
    """Check if user has reached their session limit, ignoring current device if it already has a session"""
    # Default to 1 if limit is not provided or zero
    if limit is None or limit <= 0:
        return True # Unlimited or follow system default (usually handled by Profile)
    
    conn = get_db()
    if not conn:
        return True # Fail-safe: allow if DB is down
        
    try:
        cur = conn.cursor()
        username = username.strip().lower() # Consistent lowercase
        
        # 1. If we provide current_mac, check if this specific device already has an active session
        if current_mac:
            clean_mac = current_mac.replace(':', '').replace('-', '').upper()
            cur.execute(
                "SELECT COUNT(*) FROM active_sessions WHERE username=%s AND "
                "REPLACE(REPLACE(UPPER(mac_address), ':', ''), '-', '') = %s", 
                (username, clean_mac)
            )
            if cur.fetchone()[0] > 0:
                cur.close()
                conn.close()
                return True # Allow re-login/session refresh from same device
            
        # 2. Count total active sessions for this user
        cur.execute("SELECT COUNT(*) FROM active_sessions WHERE username=%s", (username,))
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        
        log.info(f"Checking Limit: user={username} current_sessions={count} limit={limit}")
        return count < limit
    except Exception as e:
        log.error(f"Error in check_simultaneous_use: {e}")
        if conn:
            conn.close()
        return True # Fail-safe

# ─── MAIN SERVER ─────────────────────────────────────────────────
class RadiusServer:
    # ... (existing init and loop)
    def __init__(self):
        self.auth_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.acct_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def start(self):
        self.auth_sock.bind(('0.0.0.0', AUTH_PORT))
        self.acct_sock.bind(('0.0.0.0', ACCT_PORT))
        log.info(f"Auth listening on :{AUTH_PORT}")
        log.info(f"Acct listening on :{ACCT_PORT}")
        
        # Log secret info untuk debugging
        s = get_secret()
        log.info(f"RADIUS Secret (first 8 chars MD5): {hashlib.md5(s).hexdigest()[:8]}...")
        log.info(f"Default secret: {DEFAULT_SECRET if isinstance(DEFAULT_SECRET, str) else DEFAULT_SECRET.decode()}")

        threading.Thread(target=self._loop, args=(self.auth_sock, self.handle_auth), daemon=True).start()
        threading.Thread(target=self._loop, args=(self.acct_sock, self.handle_acct), daemon=True).start()

        try:
            threading.Event().wait()  # block forever
        except KeyboardInterrupt:
            log.info("Shutting down")

    def _loop(self, sock, handler):
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                threading.Thread(target=handler, args=(data, addr), daemon=True).start()
            except Exception as e:
                log.error(f"Loop error: {e}")

    # ── Authentication ────────────────────────────────────────────
    def handle_auth(self, data, addr):
        if len(data) < 20:
            return

        pkt_id = data[1]
        pkt_len = struct.unpack('!H', data[2:4])[0]
        authenticator = data[4:20]
        attrs = parse_attrs(data[20:pkt_len])

        username = attrs.get(ATTR_USER_NAME, b'').decode('utf-8', errors='ignore').strip()
        mac = attrs.get(ATTR_CALLING_STATION, b'').decode('utf-8', errors='ignore').strip()
        log.info(f"AUTH user='{username}' mac='{mac}' from={addr[0]}")

        # 0. Try MAC Authentication (IPoE/DHCP Setup)
        import re
        if re.match(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$', username):
            mac_user = find_customer_by_mac(username)
            if mac_user:
                # Check Limit Login for MAC Auth
                if not check_simultaneous_use(username, mac_user.get('shared_users'), mac):
                    log.warning(f"REJECT MAC {username}: Simultaneous-Use limit reached")
                    self._send_reject(pkt_id, authenticator, addr, "Batas Login Perangkat Tercapai")
                    return

                log.info(f"ACCEPT MAC Auth: {username}")
                self._send_accept(pkt_id, authenticator, addr,
                                  mac_user,
                                  mac_user.get('static_ip'))
                return

        # Decode PAP password for PPPoE/Hotspot
        enc_pw = attrs.get(ATTR_USER_PASSWORD)
        if not enc_pw:
            self._send_reject(pkt_id, authenticator, addr, "PAP required")
            return

        current_secret = get_secret()
        password = decode_pap_password(enc_pw, authenticator, current_secret)

        # 1. Try customer lookup (PPPoE/Member)
        user = find_customer(username)
        if user:
            # Check password
            if user['password'].strip() == password.strip():
                # Check Limit Login
                if not check_simultaneous_use(username, user.get('shared_users'), mac):
                    log.warning(f"REJECT {username}: Simultaneous-Use limit reached")
                    self._send_reject(pkt_id, authenticator, addr, "Batas Login Terlampaui")
                    return

                log.info(f"ACCEPT customer: {username}")
                self._send_accept(pkt_id, authenticator, addr,
                                  user,
                                  user.get('static_ip'))
                return
            else:
                log.warning(f"REJECT {username}: wrong password")
                self._send_reject(pkt_id, authenticator, addr, "Wrong password")
                return

        # 2. Try voucher lookup (code = username = password)
        voucher = find_voucher(username)
        if voucher:
            if password == username or password == voucher['code'] or password == "":
                # CHECK SIMULTANEOUS USE (NEW)
                if not check_simultaneous_use(username, voucher.get('shared_users'), mac):
                    log.warning(f"REJECT Voucher {username}: Simultaneous-Use limit reached")
                    self._send_reject(pkt_id, authenticator, addr, "Batas Perangkat Tercapai")
                    return

                # CHECK VALIDITY
                now = datetime.datetime.now()
                
                # If brand new (unused), verify it's not expired by creation date? (Optional, usually we don't expire unused vouchers yet)
                # But if 'active', check expiry
                if voucher['status'] == 'active':
                    if voucher.get('expires_at') and voucher['expires_at'] < now:
                        log.warning(f"REJECT voucher {username}: expired at {voucher['expires_at']}")
                        self._send_reject(pkt_id, authenticator, addr, "Voucher Expired")
                        # Update status to expired
                        try:
                            conn = get_db()
                            cur = conn.cursor()
                            cur.execute("UPDATE vouchers SET status='expired' WHERE code=%s", (username,))
                            conn.commit()
                            conn.close()
                        except: pass
                        return
                
                log.info(f"ACCEPT voucher: {username}")
                
                # Calculate Session-Timeout (Remaining seconds)
                remaining_seconds = 0
                if voucher['status'] == 'active':
                    # Already active — calculate remaining
                    if voucher.get('expires_at'):
                       remaining = (voucher['expires_at'] - now).total_seconds()
                       remaining_seconds = int(max(0, remaining))
                else:
                    # New/unused voucher — use duration from profile
                    dur = voucher.get('duration_hours', 24)
                    remaining_seconds = int(dur * 3600)

                # CHECK QUOTA (NEW)
                quota_limit = int(voucher.get('quota_limit') or voucher.get('p_quota_limit') or 0)
                quota_used = int(voucher.get('quota_used') or 0)
                
                if quota_limit > 0 and quota_used >= quota_limit:
                    log.warning(f"REJECT voucher {username}: Quota exceeded ({quota_used}/{quota_limit})")
                    self._send_reject(pkt_id, authenticator, addr, "Quota Habis")
                    return
                
                # Send Accept with Profile, Timeout & Quota  
                # (Voucher only becomes 'active' on ACCT START, not on auth accept)
                self._send_accept_voucher(pkt_id, authenticator, addr,
                                  voucher, 
                                  remaining_seconds,
                                  quota_limit,
                                  quota_used)
                return

        # 3. Not found
        log.warning(f"REJECT {username}: user not found")
        self._send_reject(pkt_id, authenticator, addr, "User not found")

    def _send_reject(self, pkt_id, authenticator, addr, message="Authentication failed"):
        """Send Access-Reject with Message-Authenticator"""
        log.info(f"  📤 Sending Access-REJECT to {addr[0]}:{addr[1]}")
        self._send_response(CODE_ACCESS_REJECT, pkt_id, authenticator, addr, 
                           [(ATTR_REPLY_MESSAGE, message)])
    
    
    def _send_response(self, code, pkt_id, authenticator, addr, reply_attrs=None):
        """Universal response builder with Message-Authenticator"""
        import hmac
        current_secret = get_secret()

        attr_bytes = b''
        if reply_attrs:
            for atype, aval in reply_attrs:
                if isinstance(aval, str):
                    aval = aval.encode('utf-8')
                elif isinstance(aval, int):
                    aval = struct.pack('!I', aval)
                attr_bytes += struct.pack('BB', atype, len(aval) + 2) + aval
        
        # 1. Add Message-Auth placeholder (Zeros)
        # We need to reconstruct the attribute block for the HMAC calculation first
        ma_attr = struct.pack('BB', ATTR_MESSAGE_AUTH, 18) + (b'\x00' * 16)
        attrs_for_hmac = attr_bytes + ma_attr
        
        # 2. Calculate Message-Authenticator (HMAC-MD5)
        # RFC 2869: Uses REQUEST Authenticator
        # Input: Code + ID + Len + RequestAuth + Attributes(with Zero MA)
        length = 20 + len(attrs_for_hmac)
        pkt_for_hmac = struct.pack('!BBH', code, pkt_id, length) + authenticator + attrs_for_hmac
        msg_auth = hmac.new(current_secret, pkt_for_hmac, hashlib.md5).digest()
        
        # 3. Update Attributes with Real Message-Authenticator
        real_ma_attr = struct.pack('BB', ATTR_MESSAGE_AUTH, 18) + msg_auth
        final_attrs = attr_bytes + real_ma_attr
        
        # 4. Calculate Response-Authenticator (MD5)
        # RFC 2865: Uses the attributes WE ARE ABOUT TO SEND (including the Real MA)
        # Input: Code + ID + Len + RequestAuth + Attributes(with Real MA) + Secret
        resp_auth_input = struct.pack('!BBH', code, pkt_id, length) + authenticator + final_attrs + current_secret
        resp_auth = hashlib.md5(resp_auth_input).digest()
        
        # 5. Build Final Packet
        final_pkt = struct.pack('!BBH', code, pkt_id, length) + resp_auth + final_attrs
        
        # DEBUG
        log.info(f"  🔍 RADIUS Response Packet ({len(final_pkt)} bytes):")
        log.info(f"     Code={code} ID={pkt_id} Len={length}")
        log.info(f"     Msg-Auth (HMAC): {msg_auth.hex()}")
        log.info(f"     Resp-Auth (MD5): {resp_auth.hex()}")
        
        self.auth_sock.sendto(final_pkt, addr)
    
    def _assemble_rate_limit(self, user):
        """Build Mikrotik Rate Limit string with Burst support"""
        rate = user.get('rate_limit')
        if not rate: return None
        
        # Normalize: convert 'm' (milli) to 'M' (Mega) as most users mistake them
        rate = str(rate).replace('m', 'M')
        
        burst_limit = str(user.get('burst_limit') or '').replace('m', 'M')
        burst_threshold = str(user.get('burst_threshold') or '').replace('m', 'M')
        burst_time = str(user.get('burst_time') or '')
        # priority is hardcoded to 8 (Standard) if space for it exists
        limit_at = str(user.get('limit_at') or '').replace('m', 'M')

        # Format: rx-rate/tx-rate [rx-burst-rate/tx-burst-rate [rx-burst-threshold/tx-burst-threshold [rx-burst-time/tx-burst-time [priority [rx-limit-at/tx-limit-at]]]]]
        # Important: Components must be in order.
        if burst_limit and burst_threshold and burst_time:
            parts = [rate, burst_limit, burst_threshold, burst_time]
            if limit_at:
                parts.append("8") # priority
                parts.append(limit_at)
            return " ".join(parts)
        
        return rate

    def _send_accept(self, pkt_id, authenticator, addr, user, static_ip=None):
        """Build and send Access-Accept with Message-Authenticator for Mikrotik"""
        rate_limit = self._assemble_rate_limit(user)
        pool_name = user.get('pool_name')
        log.info(f"  📤 Sending Access-ACCEPT to {addr[0]}:{addr[1]} rate={rate_limit} pool={pool_name} ip={static_ip}")
        import hmac
        current_secret = get_secret()
        
        # Step 1: Build regular attributes
        reply = [
            (ATTR_SERVICE_TYPE, 2),       # Framed-User
            (ATTR_FRAMED_PROTOCOL, 1),    # PPP
        ]
        if pool_name:
            # Send both standard and Mikrotik-specific pool attributes for compatibility
            reply.append((88, pool_name)) # Framed-Pool (Standard)
        if static_ip:
            try:
                reply.append((ATTR_FRAMED_IP, socket.inet_aton(static_ip)))
            except Exception as e:
                log.warning(f"Invalid Static IP format {static_ip}: {e}")
        
        attr_bytes = b''
        for atype, aval in reply:
            if isinstance(aval, str):
                aval = aval.encode('utf-8')
            elif isinstance(aval, int):
                aval = struct.pack('!I', aval)
            attr_bytes += struct.pack('BB', atype, len(aval) + 2) + aval
        
        if pool_name:
            # VSA 9 = Mikrotik-Address-Pool
            attr_bytes += make_vsa_mikrotik(9, pool_name)
        
        if rate_limit:
            attr_bytes += make_vsa_mikrotik(MIKROTIK_RATE_LIMIT_TYPE, rate_limit)
        
        # Step 2: Add Message-Authenticator placeholder (Zeros)
        ma_attr = struct.pack('BB', ATTR_MESSAGE_AUTH, 18) + (b'\x00' * 16)
        attrs_for_hmac = attr_bytes + ma_attr
        
        # Step 3: Calculate Message-Authenticator (HMAC-MD5)
        # RFC 2869: Uses REQUEST Authenticator
        length = 20 + len(attrs_for_hmac)
        pkt_for_hmac = struct.pack('!BBH', CODE_ACCESS_ACCEPT, pkt_id, length) + authenticator + attrs_for_hmac
        msg_auth = hmac.new(current_secret, pkt_for_hmac, hashlib.md5).digest()
        
        # Step 4: Update Attributes with Real Message-Authenticator
        real_ma_attr = struct.pack('BB', ATTR_MESSAGE_AUTH, 18) + msg_auth
        final_attrs = attr_bytes + real_ma_attr
        
        # Step 5: Calculate Response-Authenticator (MD5)
        # RFC 2865: Uses attributes INCLUDING Real MA
        resp_auth_input = struct.pack('!BBH', CODE_ACCESS_ACCEPT, pkt_id, length) + authenticator + final_attrs + current_secret
        resp_auth = hashlib.md5(resp_auth_input).digest()
        
        # Step 6: Build Final Packet
        final_pkt = struct.pack('!BBH', CODE_ACCESS_ACCEPT, pkt_id, length) + resp_auth + final_attrs
        
        self.auth_sock.sendto(final_pkt, addr)
    def _send_accept_voucher(self, pkt_id, authenticator, addr, voucher, session_timeout=0, quota_limit=0, quota_used=0):
        """Build Access-Accept specifically for Vouchers with Session-Timeout & Quota"""
        rate_limit = self._assemble_rate_limit(voucher)
        pool_name = voucher.get('pool_name')
        
        log.info(f"  📤 Sending Voucher ACCEPT to {addr[0]}:{addr[1]} timeout={session_timeout}s quota={quota_limit}")
        import hmac
        current_secret = get_secret()
        log.info(f"  🔑 Secret hash: {hashlib.md5(current_secret).hexdigest()[:8]}... len={len(current_secret)}")
        
        reply = [
            (ATTR_SERVICE_TYPE, 2),       # Framed-User
            (ATTR_FRAMED_PROTOCOL, 1),    # PPP
        ]
        if pool_name:
            reply.append((ATTR_FRAMED_POOL, pool_name))
        
        # Add Session-Timeout (Attribute 27)
        if session_timeout > 0:
            reply.append((ATTR_SESSION_TIMEOUT, session_timeout))
        
        attr_bytes = b''
        for atype, aval in reply:
            if isinstance(aval, str):
                aval = aval.encode('utf-8')
            elif isinstance(aval, int):
                aval = struct.pack('!I', aval)
            attr_bytes += struct.pack('BB', atype, len(aval) + 2) + aval
        
        if rate_limit:
            attr_bytes += make_vsa_mikrotik(MIKROTIK_RATE_LIMIT_TYPE, rate_limit)
        
        # Add MikroTik Address-Pool VSA (type 9) — diperlukan MikroTik untuk IP Pool
        if pool_name:
            attr_bytes += make_vsa_mikrotik(9, pool_name)
            
        # Add Quota Limit (VSA 17) - Standard Mikrotik Xmit-Limit-64 equivalent for total limit usually handled by user info
        if quota_limit > 0:
            rem_quota = max(0, quota_limit - quota_used)
            # Send limit in bytes
            attr_bytes += make_vsa_mikrotik(MIKROTIK_XMIT_LIMIT, str(rem_quota))
        
        # Message-Authenticator Logic (Required for Mikrotik)
        ma_attr = struct.pack('BB', ATTR_MESSAGE_AUTH, 18) + (b'\x00' * 16)
        attrs_for_hmac = attr_bytes + ma_attr
        
        length = 20 + len(attrs_for_hmac)
        pkt_for_hmac = struct.pack('!BBH', CODE_ACCESS_ACCEPT, pkt_id, length) + authenticator + attrs_for_hmac
        msg_auth = hmac.new(current_secret, pkt_for_hmac, hashlib.md5).digest()
        
        real_ma_attr = struct.pack('BB', ATTR_MESSAGE_AUTH, 18) + msg_auth
        final_attrs = attr_bytes + real_ma_attr
        
        resp_auth_input = struct.pack('!BBH', CODE_ACCESS_ACCEPT, pkt_id, length) + authenticator + final_attrs + current_secret
        resp_auth = hashlib.md5(resp_auth_input).digest()
        
        final_pkt = struct.pack('!BBH', CODE_ACCESS_ACCEPT, pkt_id, length) + resp_auth + final_attrs
        self.auth_sock.sendto(final_pkt, addr)
        log.info(f"  ✅ Response sent to {addr[0]}:{addr[1]}")

    # ── Accounting ────────────────────────────────────────────────
    def handle_acct(self, data, addr):
        if len(data) < 20:
            return
        pkt_id = data[1]
        pkt_len = struct.unpack('!H', data[2:4])[0]
        authenticator = data[4:20]
        attrs = parse_attrs(data[20:pkt_len])

        # Parse Standard Attributes
        username = attrs.get(ATTR_USER_NAME, b'').decode('utf-8', errors='ignore')
        acct_session_id = attrs.get(ATTR_ACCT_SESSION_ID, b'').decode('utf-8', errors='ignore')
        
        status_raw = attrs.get(ATTR_ACCT_STATUS)
        status = struct.unpack('!I', status_raw)[0] if (status_raw and len(status_raw) == 4) else 0

        # Parse Octets (Bytes) - Mikrotik sends 4-byte integers for basic attribs
        # 42=Acct-Input-Octets (Upload), 43=Acct-Output-Octets (Download)
        inp_raw = attrs.get(42)
        out_raw = attrs.get(43)
        input_octets = struct.unpack('!I', inp_raw)[0] if (inp_raw and len(inp_raw) == 4) else 0
        output_octets = struct.unpack('!I', out_raw)[0] if (out_raw and len(out_raw) == 4) else 0

        # Parse Session Time
        time_raw = attrs.get(46) # Acct-Session-Time
        session_time = struct.unpack('!I', time_raw)[0] if (time_raw and len(time_raw) == 4) else 0

        # Parse IP
        framed_ip_raw = attrs.get(ATTR_FRAMED_IP)
        framed_ip = socket.inet_ntoa(framed_ip_raw) if framed_ip_raw else addr[0]
        
        calling_station = attrs.get(ATTR_CALLING_STATION, b'').decode('utf-8', errors='ignore')

        names = {1: 'Start', 2: 'Stop', 3: 'Update', 7: 'Acct-On', 8: 'Acct-Off'}
        log.info(f"ACCT user={username} status={names.get(status, status)} dl={output_octets} ul={input_octets}")

        # ─── DATABASE LOGGING ─────────────────────────────────────────
        try:
            conn = get_db()
            if conn:
                cur = conn.cursor()
                
                # START
                if status == 1: 
                    cur.execute(
                        "INSERT INTO radacct (acctsessionid, acctuniqueid, username, realm, nasipaddress, "
                        "nasportid, nasporttype, acctstarttime, acctstoptime, acctsessiontime, "
                        "acctauthentic, connectinfo_start, connectinfo_stop, acctinputoctets, "
                        "acctoutputoctets, calledstationid, callingstationid, acctterminatecause, "
                        "servicetype, framedprotocol, framedipaddress) "
                        "VALUES (%s, %s, %s, '', %s, '', '', NOW(), NULL, 0, '', '', '', 0, 0, '', %s, '', '', '', %s)",
                        (acct_session_id, acct_session_id, username, addr[0], calling_station, framed_ip)
                    )
                    # Also update active_sessions
                    self._update_active_session(1, username, addr[0], acct_session_id, calling_station)

                # STOP
                elif status == 2:
                    term_cause = attrs.get(49) # Acct-Terminate-Cause
                    if term_cause: term_cause = str(struct.unpack('!I', term_cause)[0])
                    else: term_cause = ''

                    cur.execute(
                        "UPDATE radacct SET acctstoptime=NOW(), acctsessiontime=%s, "
                        "acctinputoctets=%s, acctoutputoctets=%s, acctterminatecause=%s "
                        "WHERE acctsessionid=%s AND username=%s",
                        (session_time, input_octets, output_octets, term_cause, acct_session_id, username)
                    )
                    # Also update active_sessions
                    self._update_active_session(2, username, addr[0], acct_session_id, calling_station)

                # INTERIM-UPDATE (Alive)
                elif status == 3:
                     cur.execute(
                        "UPDATE radacct SET acctupdatetime=NOW(), acctsessiontime=%s, "
                        "acctinputoctets=%s, acctoutputoctets=%s, framedipaddress=%s "
                        "WHERE acctsessionid=%s AND username=%s",
                        (session_time, input_octets, output_octets, framed_ip, acct_session_id, username)
                    )
                     # Also update active_sessions
                     self._update_active_session(3, username, addr[0], acct_session_id, calling_station)
                
                # ACCT-ON / ACCT-OFF (Router Reboot)
                elif status in (7, 8):
                    log.info(f"NAS {addr[0]} REBOOTED (Status={status}). Clearing active sessions.")
                    cur.execute("DELETE FROM active_sessions WHERE nas_ip=%s", (addr[0],))
                
                conn.commit()
                cur.close()
                conn.close()

        except Exception as e:
            log.error(f"DB Error handle_acct: {e}")
        # ──────────────────────────────────────────────────────────────

        # Always respond OK
        self.acct_sock.sendto(
            make_response(CODE_ACCT_RESPONSE, pkt_id, authenticator, get_secret()),
            addr
        )

    def _update_active_session(self, status, username, nas_ip, session_id, mac_address=None):
        """Update active_sessions table based on Acct-Status-Type"""
        username = username.strip().lower() if username else ""
        try:
            conn = get_db()
            if not conn: return
            cur = conn.cursor()
            
            if status == 1: # Start
                cur.execute(
                    "INSERT IGNORE INTO active_sessions (username, nas_ip, acct_session_id, mac_address) VALUES (%s, %s, %s, %s)",
                    (username, nas_ip, session_id, mac_address)
                )
                try:
                    # 1. Identify NAS ID
                    nas_id = None
                    try:
                        cur.execute("SELECT id FROM routers WHERE ip_address=%s OR vpn_ip=%s OR vpn_ip LIKE %s LIMIT 1", 
                                    (nas_ip, nas_ip, f"%{nas_ip}%"))
                        r = cur.fetchone()
                        if r:
                            nas_id = r['id'] if isinstance(r, dict) else r[0]
                    except Exception as sql_err:
                        # If ip_address column missing (during migration), fallback to vpn_ip only
                        cur.execute("SELECT id FROM routers WHERE vpn_ip=%s OR vpn_ip LIKE %s LIMIT 1", 
                                    (nas_ip, f"%{nas_ip}%"))
                        r = cur.fetchone()
                        if r:
                            nas_id = r['id'] if isinstance(r, dict) else r[0]

                    # 2. Check if this is actually a Voucher
                    cur.execute("SELECT id, duration_hours FROM vouchers WHERE code=%s LIMIT 1", (username,))
                    vrow = cur.fetchone()
                    if vrow:
                        dur = vrow.get('duration_hours', 24) if isinstance(vrow, dict) else (vrow[1] if len(vrow) > 1 else 24)
                        if nas_id:
                            cur.execute(
                                "UPDATE vouchers SET session_id=%s, nas_id=%s, status='active', activated_at=NOW(), "
                                "expires_at=DATE_ADD(NOW(), INTERVAL %s HOUR) WHERE code=%s AND status IN ('unused', 'active')",
                                (session_id, nas_id, dur, username)
                            )
                        else:
                            cur.execute(
                                "UPDATE vouchers SET session_id=%s, status='active', activated_at=NOW(), "
                                "expires_at=DATE_ADD(NOW(), INTERVAL %s HOUR) WHERE code=%s AND status IN ('unused', 'active')",
                                (session_id, dur, username)
                            )
                except Exception as ex:
                    log.error(f"Fail update voucher nas info: {ex}")
            elif status == 2: # Stop
                cur.execute(
                    "DELETE FROM active_sessions WHERE username=%s AND acct_session_id=%s",
                    (username, session_id)
                )
            elif status == 3: # Update / Interim-Update
                cur.execute(
                    "UPDATE active_sessions SET updated_at=NOW() WHERE username=%s AND acct_session_id=%s",
                    (username, session_id)
                )
            
            # --- QUOTA TRACKING (NEW) ---
            if status in [2, 3]: # Stop or Interim Update
                # Calculate total usage from radacct for this session
                # Or use the input/output octets provided in the packet
                # Simplest: Update the voucher's quota_used based on THIS ACCT packet's bytes
                # But packets are cumulative in a session usually, so we should actually 
                # calculate the total usage for the username overall or per session.
                # Let's sum all radacct for this username to be safe.
                cur.execute(
                    "UPDATE vouchers v SET v.quota_used = (SELECT SUM(acctinputoctets + acctoutputoctets) FROM radacct WHERE username=%s) "
                    "WHERE v.code = %s",
                    (username, username)
                )
            
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            log.error(f"DB Error _update_active_session: {e}")
            if conn: conn.close()


if __name__ == '__main__':
    log.info("=" * 50)
    log.info(" MikroFun RADIUS Server v1.0")
    log.info(f" Config: {CONFIG_STATUS}")
    log.info(f" DB: {DB_USER}@{DB_HOST}/{DB_NAME}")
    log.info(" Auth: 0.0.0.0:1812  Acct: 0.0.0.0:1813")
    log.info("=" * 50)
    server = RadiusServer()
    server.start()
