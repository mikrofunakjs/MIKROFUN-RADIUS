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


def start_wa_reminder():
    """Background loop — check every 3600 seconds (1 hour)"""
    print("[WA Reminder] Service started (checks every hour)...")
    while True:
        try:
            run()
        except Exception as e:
            print(f"[WA Reminder] Error: {e}")
        time.sleep(3600)


if __name__ == '__main__':
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] WA Reminder started.")
    sent = run()
    print(f"Done. Sent {sent} reminders.")
