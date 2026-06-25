#!/usr/bin/env python3
"""
Auto Isolate Service — runs as background thread.
- Checks for PPPoE customers past due_date every 60 seconds.
- Isolates them (status='isolir'), kicks from MikroTik, sends WA notification.
"""
import sys
import os
import time
import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from web.database import execute_query


def try_api_disconnect(router_data, username):
    """Kick user from MikroTik via API"""
    if not router_data or not router_data.get('vpn_ip') or not router_data.get('api_user'):
        return False, "Router API not configured"

    try:
        from web.mikrotik_api import MikrotikApi
        api = MikrotikApi(router_data['vpn_ip'], int(router_data.get('api_port') or 8728))
        if not api.login(router_data['api_user'], router_data['api_password']):
            return False, "API Login Failed"
        success, msg = api.kick_user(username)
        api.close()
        return success, msg
    except Exception as e:
        return False, str(e)


def run_auto_isolate():
    """Check and isolate expired customers once"""
    customers = execute_query(
        """SELECT c.*, r.vpn_ip, r.api_user, r.api_password, r.api_port 
           FROM customers c
           LEFT JOIN routers r ON c.router_id = r.id
           WHERE c.status = 'active' 
             AND c.due_date IS NOT NULL 
             AND c.due_date < CURDATE()""",
        fetch=True
    ) or []

    if not customers:
        return 0

    count = 0
    for c in customers:
        print(f"[Auto-Isolate] Isolating {c['name']} (Due: {c['due_date']})")

        # 1. Update status
        execute_query("UPDATE customers SET status='isolir' WHERE id=%s", (c['id'],))

        # 2. Kick from router
        kick_status = "Skipped API"
        if c.get('vpn_ip') and c.get('api_user'):
            success, msg = try_api_disconnect(c, c['username'])
            kick_status = "Kicked via API" if success else f"Kick Failed ({msg})"

        # 3. Clear active sessions
        execute_query("DELETE FROM active_sessions WHERE username=%s", (c['username'],))

        # 4. Notifikasi WA (isolir_warning)
        if c.get('phone'):
            try:
                from web.wa_helper import send_wa_notification
                due_str = c['due_date'].strftime('%d/%m/%Y') if c['due_date'] else ''
                send_wa_notification(
                    c['phone'], 'isolir_warning',
                    name=c['name'], due_date=due_str,
                    fallback_message=f"Halo {c['name']}, layanan internet Anda telah dihentikan karena melewati jatuh tempo {due_str}. Segera lakukan pembayaran untuk mengaktifkan kembali."
                )
            except Exception as e:
                print(f"  WA notification failed: {e}")

        # 5. System notification
        try:
            from web.blueprints.notifications import add_notification
            add_notification(
                title="Auto-Isolir",
                message=f"Pelanggan {c['name']} ({c['username']}) diisolir otomatis. Due: {c['due_date']}. {kick_status}",
                category="danger"
            )
        except Exception:
            pass

        count += 1

    return count


def start_auto_isolate():
    """Background loop — run every 60 seconds"""
    print("[Auto-Isolate] Service started (checks every 60s)...")
    while True:
        try:
            processed = run_auto_isolate()
            if processed > 0:
                print(f"[Auto-Isolate] Processed {processed} customers.")
        except Exception as e:
            print(f"[Auto-Isolate] Error: {e}")
        time.sleep(60)


if __name__ == '__main__':
    print(f"--- Running Auto Isolate at {datetime.datetime.now()} ---")
    processed = run_auto_isolate()
    print(f"--- Done. Processed {processed} customers. ---")
