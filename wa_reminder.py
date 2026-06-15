#!/usr/bin/env python3
"""
WA Reminder Cron Script
Kirim notifikasi WA ke pelanggan yang tagihannya akan jatuh tempo dalam N hari.
Jalankan via cron, contoh setiap jam 08:00:
  0 8 * * * /opt/mikrofun/venv/bin/python /opt/mikrofun/wa_reminder.py
"""
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir) if current_dir != '.' else os.getcwd()
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

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
    print(f"[{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] WA Reminder started.")

    ensure_reminder_table()

    # Baca setting
    enabled_row = execute_query(
        "SELECT setting_value FROM settings WHERE setting_key='wa_reminder_enabled'", fetch_one=True
    )
    enabled = enabled_row['setting_value'] if enabled_row else '1'
    if enabled != '1':
        print("WA Reminder disabled. Exiting.")
        return

    days_row = execute_query(
        "SELECT setting_value FROM settings WHERE setting_key='wa_reminder_days'", fetch_one=True
    )
    days_before = int(days_row['setting_value']) if days_row and days_row['setting_value'].isdigit() else 3

    print(f"Looking for customers with due_date in {days_before} day(s)...")

    # Query customer yang due_date = TODAY + N days
    import datetime
    target_date = datetime.date.today() + datetime.timedelta(days=days_before)

    customers = execute_query(
        """SELECT id, name, username, phone, due_date 
           FROM customers 
           WHERE status = 'active' 
             AND due_date = %s 
             AND phone IS NOT NULL 
             AND phone != ''""",
        (target_date,), fetch=True
    )

    if not customers:
        print("No customers to remind today.")
        return

    sent_count = 0
    skip_count = 0
    fail_count = 0

    for c in customers:
        due_str = c['due_date'].strftime('%d/%m/%Y') if c['due_date'] else ''

        # Cek apakah sudah pernah dikirim untuk due_date ini
        already = execute_query(
            "SELECT id FROM wa_reminders_sent WHERE customer_id=%s AND due_date=%s",
            (c['id'], c['due_date']), fetch_one=True
        )
        if already:
            skip_count += 1
            continue

        # Kirim WA
        try:
            ok = send_wa_notification(
                c['phone'], 'isolir_warning',
                name=c['name'], due_date=due_str,
                fallback_message=f"Halo {c['name']}, layanan internet Anda akan segera habis pada {due_str}. Segera lakukan pembayaran untuk menghindari pemutusan."
            )
            if ok:
                execute_query(
                    "INSERT INTO wa_reminders_sent (customer_id, due_date) VALUES (%s, %s)",
                    (c['id'], c['due_date'])
                )
                sent_count += 1
                print(f"  [SENT] {c['name']} ({c['username']}) -> {c['phone']}")
            else:
                fail_count += 1
                print(f"  [FAIL] {c['name']} ({c['username']}) -> {c['phone']}")
        except Exception as e:
            fail_count += 1
            print(f"  [ERR] {c['name']} ({c['username']}): {e}")

    print(f"Done. Sent: {sent_count}, Skipped: {skip_count}, Failed: {fail_count}")

if __name__ == "__main__":
    run()
