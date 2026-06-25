import os
import sys
import shutil
import multiprocessing

# Clean stale __pycache__ before any project imports (prevents stale bytecode from overriding updated code)
_self_dir = os.path.dirname(os.path.abspath(__file__))
for _root, _dirs, _files in os.walk(_self_dir):
    for _d in _dirs:
        if _d == '__pycache__':
            _cache_path = os.path.join(_root, _d)
            try:
                shutil.rmtree(_cache_path, ignore_errors=True)
            except Exception:
                pass

if __name__ == '__main__':
    multiprocessing.freeze_support()

from web.app import app
from waitress import serve
from simple_radius import RadiusServer
import threading

# Force Include for PyInstaller
import requests
import certifi
import urllib3
import web.wa_helper
import web.backup_helper
import web.tripay_helper
import web.midtrans_helper

# Configure Port (Default 80 or env)
PORT = int(os.environ.get('PORT', 80))

print(f"Starting MikroFun Radius (Binary Version)...")
print(f"Version: {app.config.get('APP_VERSION', 'Unknown')}")

from monitor_router_status import start_monitor
from cleanup_vouchers import start_cleanup
from auto_isolate import start_auto_isolate
from wa_reminder import start_wa_reminder

# Auto-Heal Database Schema before starting threads
try:
    from web.database import execute_query
    print("Auto-Healing Database Schema...")
    # Add payment_channel if missing
    schema = execute_query("SHOW COLUMNS FROM payments LIKE 'payment_channel'", fetch_one=True)
    if not schema:
        execute_query("ALTER TABLE payments ADD COLUMN payment_channel VARCHAR(32)")
        
    # Add external_ref if missing
    schema = execute_query("SHOW COLUMNS FROM payments LIKE 'external_ref'", fetch_one=True)
    if not schema:
        execute_query("ALTER TABLE payments ADD COLUMN external_ref VARCHAR(64)")
        
    # Add checkout_url if missing
    schema = execute_query("SHOW COLUMNS FROM payments LIKE 'checkout_url'", fetch_one=True)
    if not schema:
        execute_query("ALTER TABLE payments ADD COLUMN checkout_url TEXT")
        
    # Auto-create technician_jobs table for v7.3.0
    execute_query("""
    CREATE TABLE IF NOT EXISTS technician_jobs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        ticket_id INT NULL,
        customer_id INT NULL,
        technician_id INT NULL,
        job_type VARCHAR(64) NOT NULL,
        title VARCHAR(128) NOT NULL,
        description TEXT,
        priority ENUM('low', 'medium', 'high', 'urgent') DEFAULT 'medium',
        status ENUM('pending', 'on_way', 'working', 'resolved', 'cancelled') DEFAULT 'pending',
        scheduled_date DATETIME NULL,
        completed_at DATETIME NULL,
        evidence_photo_1 VARCHAR(255) NULL,
        evidence_photo_2 VARCHAR(255) NULL,
        resolution_notes TEXT,
        created_by INT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (technician_id) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL
    )
    """)
    
    # Auto-add Voucher E-Commerce columns to payments table
    p_schema = execute_query("SHOW COLUMNS FROM payments LIKE 'payment_type'", fetch_one=True)
    if not p_schema:
        execute_query("ALTER TABLE payments ADD COLUMN payment_type ENUM('bill', 'voucher') DEFAULT 'bill'")
        execute_query("ALTER TABLE payments ADD COLUMN profile_id INT NULL")
        execute_query("ALTER TABLE payments ADD COLUMN voucher_code VARCHAR(64) NULL")
        
except Exception as e:
    print(f"Schema Auto-Healer failed: {e}")

# Start RADIUS Server in Background Thread
def start_radius():
    print("Initializing RADIUS Server service...")
    try:
        radius = RadiusServer()
        radius.start()
    except Exception as e:
        print(f"RADIUS Server Failed to Start: {e}")

# Start Node.js Baileys WA Service
def start_wa_service():
    """Auto-start the Node.js WhatsApp Baileys gateway if available"""
    wa_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wa-service')
    server_js = os.path.join(wa_dir, 'server.js')
    if not os.path.exists(server_js):
        print("[WA Service] wa-service/server.js not found — skipping")
        return
    if not os.path.exists(os.path.join(wa_dir, 'node_modules')):
        print("[WA Service] node_modules not installed — run 'npm install' in wa-service/")
        return
    try:
        import subprocess
        subprocess.Popen(
            ['node', 'server.js'],
            cwd=wa_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("[WA Service] Node.js Baileys started on port 3000")
    except Exception as e:
        print(f"[WA Service] Failed to start: {e}")

# Threads
radius_thread = threading.Thread(target=start_radius, daemon=True)
radius_thread.start()

monitor_thread = threading.Thread(target=start_monitor, daemon=True)
monitor_thread.start()

cleanup_thread = threading.Thread(target=start_cleanup, daemon=True)
cleanup_thread.start()

isolate_thread = threading.Thread(target=start_auto_isolate, daemon=True)
isolate_thread.start()

reminder_thread = threading.Thread(target=start_wa_reminder, daemon=True)
reminder_thread.start()

# Start Node.js WA service (runs as subprocess, not thread)
start_wa_service()

print(f"Starting Web Panel on port {PORT}...")
print("Press Ctrl+C to stop.")

# Run Waitress Server
serve(app, host='0.0.0.0', port=PORT, threads=6)
