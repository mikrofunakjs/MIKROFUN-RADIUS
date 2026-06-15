#!/usr/bin/env python3
"""
Auto Isolate Script
Run this via Cron (e.g., daily at 00:01) to isolate expired customers.
"""
import mysql.connector
import datetime
import sys
import os

# --- Path auto-detection ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from web.config import DB_CONFIG
    DB_HOST = DB_CONFIG['host']
    DB_USER = DB_CONFIG['user']
    DB_PASS = DB_CONFIG['password']
    DB_NAME = DB_CONFIG['database']
except ImportError:
    # Fallback default
    DB_HOST = 'localhost'
    DB_USER = 'radius'
    DB_PASS = 'radiuspass123'
    DB_NAME = 'radius_db'

def get_db():
    try:
        return mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME)
    except Exception as e:
        print(f"DB Connection Error: {e}")
        return None

def add_notification(title, message, category='warning'):
    try:
        conn = get_db()
        if not conn: return
        cur = conn.cursor()
        cur.execute("INSERT INTO notifications (title, message, category, created_at) VALUES (%s, %s, %s, NOW())", (title, message, category))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Notification Error: {e}")

def try_api_disconnect(router_data, username):
    """Helper to disconnect user via Mikrotik API"""
    if not router_data or not router_data.get('vpn_ip') or not router_data.get('api_user'):
        return False, "Router API not configured"
        
    try:
        # Import from web.mikrotik_api correctly
        from web.mikrotik_api import MikrotikApi
        
        api = MikrotikApi(router_data['vpn_ip'], int(router_data.get('api_port') or 8728))
        if not api.login(router_data['api_user'], router_data['api_password']):
            return False, "API Login Failed"
            
        success, msg = api.kick_user(username)
        api.close()
        return success, msg
    except Exception as e:
        return False, f"API Exception: {e}"

def run_auto_isolate():
    conn = get_db()
    if not conn:
        return

    cur = conn.cursor(dictionary=True)
    
    # Select active customers with past due_date (ignoring future dates)
    query = """
    SELECT c.*, r.vpn_ip, r.api_user, r.api_password, r.api_port 
    FROM customers c
    LEFT JOIN routers r ON c.router_id = r.id
    WHERE c.status='active' 
    AND c.due_date IS NOT NULL 
    AND c.due_date < CURDATE()
    """
    
    cur.execute(query)
    expired_customers = cur.fetchall()
    
    count = 0
    for c in expired_customers:
        print(f"Isolating {c['name']} (Due: {c['due_date']})")
        
        # 1. Update DB Status to 'isolir'
        update_cur = conn.cursor()
        update_cur.execute("UPDATE customers SET status='isolir' WHERE id=%s", (c['id'],))
        conn.commit()
        
        # 2. Kick from Router (Force PPPoE/Hotspot termination)
        kick_status = "Skipped API"
        if c['vpn_ip'] and c['api_user']:
            success, msg = try_api_disconnect(c, c['username'])
            kick_status = f"Kicked via API" if success else f"Kick Failed ({msg})"
            
        # 3. Notification
        add_notification(
            title="Sistem Auto-Isolir",
            message=f"Pelanggan {c['name']} ({c['username']}) telah diisolir otomatis karena melewati jatuh tempo {c['due_date']}. {kick_status}",
            category="danger"
        )
        count += 1
        
    print(f"Successfully processed {count} customers.")
    cur.close()
    conn.close()

if __name__ == "__main__":
    print(f"--- Running Auto Isolate at {datetime.datetime.now()} ---")
    run_auto_isolate()
    print("--- Done ---")
