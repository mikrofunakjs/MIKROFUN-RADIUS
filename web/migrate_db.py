#!/usr/bin/env python3
import mysql.connector
import sys

# DATABASE CONFIG (Sesuaikan jika beda)
DB_HOST = 'localhost'
DB_USER = 'radius'
DB_PASS = 'radiuspass123'
DB_NAME = 'radius_db'

def migrate():
    print("--- MIGRATION START ---")
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME
        )
        cur = conn.cursor()
        print("[*] Connected to database.")
    except Exception as e:
        print(f"[!] Connection Failed: {e}")
        return

    # 1. Check/Add api_user
    try:
        cur.execute("SELECT api_user FROM routers LIMIT 1")
        print("[OK] Column 'api_user' exists.")
    except:
        print("[*] Adding column 'api_user'...")
        cur.execute("ALTER TABLE routers ADD COLUMN api_user VARCHAR(64)")

    # 2. Check/Add api_password
    try:
        cur.execute("SELECT api_password FROM routers LIMIT 1")
        print("[OK] Column 'api_password' exists.")
    except:
        print("[*] Adding column 'api_password'...")
        cur.execute("ALTER TABLE routers ADD COLUMN api_password VARCHAR(64)")

    # 3. Check/Add api_port
    try:
        cur.execute("SELECT api_port FROM routers LIMIT 1")
        print("[OK] Column 'api_port' exists.")
    except:
        print("[*] Adding column 'api_port'...")
        cur.execute("ALTER TABLE routers ADD COLUMN api_port INT DEFAULT 8728")

    conn.commit()
    conn.close()
    print("--- MIGRATION SUCCESS ---")
    print("Database is ready for Mikrotik API features.")

if __name__ == "__main__":
    migrate()
