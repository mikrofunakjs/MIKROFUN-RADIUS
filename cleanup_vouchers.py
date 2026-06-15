#!/usr/bin/env python3
"""
Voucher Cleanup Service
- Checks for vouchers that have expired.
- Disconnects users from Mikrotik (via API).
- Updates database status to 'expired'.
- Safe for PPPoE (only touches 'vouchers' table).
"""
import time
import logging
import datetime
import sys
import mysql.connector
from web.mikrotik_api import MikrotikApi

# Config (Should match simple_radius.py)
DB_HOST = 'localhost'
DB_USER = 'radius'
DB_PASS = 'radiuspass123'
DB_NAME = 'radius_db'

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('/var/log/mikrofun-cleanup.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger('cleanup')

def get_db():
    try:
        return mysql.connector.connect(
            host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME
        )
    except Exception as e:
        log.error(f"DB Connect Error: {e}")
        return None

def kick_user_from_mikrotik(nas_ip, username):
    """Connect to Router and Kick User"""
    # 1. Get Router Credentials from DB
    conn = get_db()
    if not conn: return False
    
    try:
        cur = conn.cursor(dictionary=True)
        # Find router by VPN IP or LAN IP (implied NAS IP)
        # Simple match for now: we assume nas_ip matches vpn_ip in DB
        cur.execute("SELECT * FROM routers WHERE vpn_ip = %s", (nas_ip,))
        router = cur.fetchone()
        cur.close()
        conn.close()
        
        if not router:
            log.warning(f"Router {nas_ip} not found in DB for user {username}")
            return False

        # 2. Connect API
        api = MikrotikApi(router['vpn_ip'], router.get('api_port', 8728))
        if not api.connect():
            log.error(f"Failed to connect to router {router['name']} ({router['vpn_ip']})")
            return False
            
        if not api.login(router['api_user'], router['api_password']):
            log.error(f"Auth failed for router {router['name']}")
            api.close()
            return False
            
        # 3. Kick
        success, msg = api.kick_user(username)
        api.close()
        log.info(f"Kick result for {username} @ {router['name']}: {msg}")
        return success

    except Exception as e:
        log.error(f"Error kicking {username}: {e}")
        if conn: conn.close()
        return False

def check_and_expire_vouchers():
    conn = get_db()
    if not conn: return

    try:
        cur = conn.cursor(dictionary=True)
        
        # 1. Find ACTIVE vouchers that have EXPIRED
        # Now > expires_at
        cur.execute(
            "SELECT code, expires_at FROM vouchers "
            "WHERE status = 'active' AND expires_at < NOW()"
        )
        expired_vouchers = cur.fetchall()
        
        if not expired_vouchers:
            return # Nothing to do

        log.info(f"Found {len(expired_vouchers)} expired vouchers...")

        for v in expired_vouchers:
            username = v['code']
            log.info(f"Processing expired voucher: {username}")
            
            # A. Update DB Status
            cur.execute("UPDATE vouchers SET status='expired' WHERE code=%s", (username,))
            conn.commit()
            
            # B. Find Active Session to Kick
            # Check active_sessions table
            cur.execute(
                "SELECT nas_ip FROM active_sessions WHERE username=%s LIMIT 1", 
                (username,)
            )
            session = cur.fetchone()
            
            if session:
                log.info(f"User {username} is online at {session['nas_ip']}. Kicking...")
                kick_user_from_mikrotik(session['nas_ip'], username)
                
                # Cleanup session record
                cur.execute("DELETE FROM active_sessions WHERE username=%s", (username,))
                conn.commit()
            else:
                log.info(f"User {username} is not currently in active_sessions.")

        cur.close()
        conn.close()

    except Exception as e:
        log.error(f"Error in cleanup loop: {e}")
        if conn: conn.close()

def start_cleanup():
    log.info("Starting Voucher Cleanup Service...")
    while True:
        try:
            check_and_expire_vouchers()
        except Exception as e:
            log.error(f"Main loop error: {e}")
        
        # Run every 60 seconds
        time.sleep(60)

if __name__ == '__main__':
    start_cleanup()
