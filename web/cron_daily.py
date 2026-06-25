#!/usr/bin/env python3
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from database import execute_query
from telegram_helper import send_telegram_message

def generate_daily_report():
    print("[*] Generating Daily Report...")
    
    try:
        # Active Customers PPPoE and MAC
        active_pppoe = execute_query("SELECT COUNT(*) as c FROM customers WHERE service_type='pppoe' AND status='active'", fetch_one=True)
        
        # Active MAC/DHCP customers (non-PPPoE)
        active_mac = execute_query("SELECT COUNT(*) as c FROM customers WHERE (service_type != 'pppoe' OR service_type IS NULL) AND status='active'", fetch_one=True)
        
        nunggak_cust = execute_query("SELECT COUNT(*) as c FROM customers WHERE status IN ('expired', 'isolir')", fetch_one=True)
        
        # Today's Income
        daily_income = execute_query(
            "SELECT SUM(amount) as total FROM payments WHERE status IN ('approved', 'PAID') "
            "AND DATE(payment_date) = CURRENT_DATE()", 
            fetch_one=True
        )
        
        # Pending Payments
        pending_payments = execute_query("SELECT COUNT(*) as c FROM payments WHERE status = 'pending'", fetch_one=True)
        
        c_pppoe = active_pppoe['c'] if active_pppoe else 0
        c_mac = active_mac['c'] if active_mac else 0
        c_nunggak = nunggak_cust['c'] if nunggak_cust else 0
        income = daily_income['total'] if daily_income and daily_income['total'] else 0
        pending = pending_payments['c'] if pending_payments else 0
        
        income_str = "{:,.0f}".format(income).replace(',', '.')
        
        report_msg = (
            "📊 *LAPORAN HARIAN MIKROFUN*\n\n"
            "*Keuangan Hari Ini:*\n"
            f"💰 Pendapatan: Rp {income_str}\n"
            f"⏳ Menunggu Dibayar: {pending} trx\n\n"
            "*Status Pelanggan:*\n"
            f"🟢 PPPoE Aktif: {c_pppoe} user\n"
            f"🟢 Internet DHCP Aktif: {c_mac} user\n"
            f"🔴 Nunggak/Isolir: {c_nunggak} user\n\n"
            "_Laporan ini di-generate rutin oleh sistem._"
        )
        
        success, err = send_telegram_message(report_msg)
        if success:
            print("[+] Daily Report sent to Telegram successfully.")
        else:
            print(f"[-] Failed to send Telegram report: {err}")
            
    except Exception as e:
        print(f"[!] Critical error generating report: {e}")

if __name__ == "__main__":
    generate_daily_report()
