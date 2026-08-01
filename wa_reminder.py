#!/usr/bin/env python3
"""
WA Reminder Service — runs as background thread.
- Checks for customers whose due_date is N days from now.
- Sends WhatsApp notification via configured provider.
- Deduplicates via wa_reminders_sent table.
"""
import sys
import os
import time
import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from web.database import execute_query
from web.wa_helper import send_wa_notification


def ensure_reminder_table():
    execute_query("""
        CREATE TABLE IF NOT EXISTS wa_reminders_sent (
            id INT AUTO_INCREMENT PRIMARY KEY,
            customer_id INT NOT NULL,
            due_date DATE NOT NULL,
            sent_at DATETIME DEFAULT NOW(),
            UNIQUE KEY uk_customer_due (customer_id, due_date)
        )
    """)


def run():
    """Check and send reminders once"""
    ensure_reminder_table()

    # Read settings
    enabled_row = execute_query(
        "SELECT setting_value FROM settings WHERE setting_key='wa_reminder_enabled'", fetch_one=True
    )
    enabled = enabled_row['setting_value'] if enabled_row else '1'
    if enabled != '1':
        return 0  # Disabled

    days_row = execute_query(
        "SELECT setting_value FROM settings WHERE setting_key='wa_reminder_days'", fetch_one=True
    )
    days_before = int(days_row['setting_value']) if days_row and days_row['setting_value'].isdigit() else 3

    target_date = datetime.date.today() + datetime.timedelta(days=days_before)

    customers = execute_query(
        """SELECT id, name, username, phone, due_date 
           FROM customers 
           WHERE status = 'active' 
             AND due_date = %s 
             AND phone IS NOT NULL 
             AND phone != ''""",
        (target_date,), fetch=True
    ) or []

    if not customers:
        return 0

    sent_count = 0
    skip_count = 0
    fail_count = 0

    for c in customers:
        due_str = c['due_date'].strftime('%d/%m/%Y') if c['due_date'] else ''

        # Check dedup
        already = execute_query(
            "SELECT id FROM wa_reminders_sent WHERE customer_id=%s AND due_date=%s",
            (c['id'], c['due_date']), fetch_one=True
        )
        if already:
            skip_count += 1
            continue

        # Send WA
        try:
            ok = send_wa_notification(
                c['phone'], 'isolir_warning',
                name=c['name'], due_date=due_str,
                fallback_message=(
                    f"Halo {c['name']}, layanan internet Anda akan segera habis "
                    f"pada {due_str}. Segera lakukan pembayaran untuk menghindari pemutusan."
                )
            )
            if ok:
                execute_query(
                    "INSERT INTO wa_reminders_sent (customer_id, due_date) VALUES (%s, %s)",
                    (c['id'], c['due_date'])
                )
                sent_count += 1
                print(f"  [WA SENT] {c['name']} ({c['username']}) -> {c['phone']}")
            else:
                fail_count += 1
                print(f"  [WA FAIL] {c['name']} ({c['username']}) -> {c['phone']}")
        except Exception as e:
            fail_count += 1
            print(f"  [WA ERR] {c['name']} ({c['username']}): {e}")

    if sent_count > 0 or fail_count > 0:
        print(f"[WA Reminder] Sent: {sent_count}, Skipped: {skip_count}, Failed: {fail_count}")

    return sent_count


def _ai_noc_check():
    """AI NOC — proactive: detect anomalies, diagnose, auto-fix if confident."""
    try:
        from ai_noc.diagnosis import diagnose as ai_diag
    except Exception:
        return

    issues = []

    # 1. Router offline >30 min
    dead = execute_query(
        """SELECT name, vpn_ip, status FROM routers
           WHERE status='offline'
             AND last_seen < DATE_SUB(NOW(), INTERVAL 30 MINUTE)""",
        fetch=True
    ) or []
    for r in dead:
        rpt = ai_diag(f"Router {r['name']} ({r['vpn_ip']}) offline >30 menit")
        issues.append(f"[ROUTER DOWN] {r['name']}: {rpt.get('diagnosis', '?')[:200]}")

    # 2. Users active session but zero traffic 30min
    zombies = execute_query(
        """SELECT a.username FROM active_sessions a
           WHERE NOT EXISTS (
               SELECT 1 FROM radacct_snapshots s
               WHERE s.username = a.username
                 AND s.snapshot_time >= DATE_SUB(NOW(), INTERVAL 30 MINUTE)
           )
           LIMIT 10""",
        fetch=True
    ) or []
    for z in zombies:
        rpt = ai_diag("User aktif tapi nol traffic 30 menit", username=z['username'])
        issues.append(f"[ZOMBIE SESSION] {z['username']}: {rpt.get('diagnosis', '?')[:200]}")

    # 3. Auth failure spike
    spike = execute_query(
        """SELECT username, COUNT(*) as cnt FROM radpostauth
           WHERE reply='Access-Reject' AND authdate >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
           GROUP BY username HAVING cnt >= 5""",
        fetch=True
    ) or []
    for s in spike:
        rpt = ai_diag(f"Auth failure spike: {s['cnt']}x dalam 1 jam", username=s['username'])
        issues.append(f"[AUTH SPIKE] {s['username']} ({s['cnt']}x): {rpt.get('diagnosis', '?')[:200]}")

    if issues:
        print(f"[AI NOC] {len(issues)} issues detected:")
        for i in issues:
            print(f"  {i}")
    return len(issues)


def _daily_ai_report():
    """Ponytail: daily DeepSeek report, runs once per day after 06:00."""
    import datetime as _dt
    now = _dt.datetime.now()
    if now.hour != 6:
        return

    try:
        from ai_noc.deepseek_client import chat as ai_chat
    except Exception:
        return

    total_users = execute_query("SELECT COUNT(*) as cnt FROM active_sessions", fetch_one=True)
    total_customers = execute_query("SELECT COUNT(*) as cnt FROM customers WHERE status='active'", fetch_one=True)
    today_income = execute_query(
        "SELECT COALESCE(SUM(amount), 0) as total FROM payments WHERE created_at >= CURDATE() AND status='paid'",
        fetch_one=True
    )

    stats = f"User online: {total_users.get('cnt', 0) if total_users else 0}\n" \
            f"Pelanggan: {total_customers.get('cnt', 0) if total_customers else 0}\n" \
            f"Pendapatan: Rp {today_income.get('total', 0) if today_income else 0:,}"

    report = ai_chat(
        "Anda AI NOC reporter MikroFun. Buat laporan harian singkat Bahasa Indonesia. "
        "Format: ringkasan, insiden, rekomendasi. Maks 300 kata.",
        f"Data MikroFun hari ini ({_dt.date.today()}):\n{stats}\n\nBuat laporan harian."
    )

    if report:
        print(f"[AI Report] {report[:200]}...")


def start_wa_reminder():
    """Background loop — check every 3600 seconds (1 hour)"""
    print("[WA Reminder] Service started (checks every hour)...")
    while True:
        try:
            run()
            _ai_noc_check()
            _daily_ai_report()
        except Exception as e:
            print(f"[WA Reminder] Error: {e}")
        time.sleep(3600)


if __name__ == '__main__':
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] WA Reminder started.")
    sent = run()
    print(f"Done. Sent {sent} reminders.")
