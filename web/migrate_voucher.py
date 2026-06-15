#!/usr/bin/env python3
import mysql.connector

# DATABASE CONFIG
DB_HOST = 'localhost'
DB_USER = 'radius'
DB_PASS = 'radiuspass123'
DB_NAME = 'radius_db'

def migrate():
    print("--- MIGRATION VOUCHER START ---")
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME
        )
        cur = conn.cursor()
    except Exception as e:
        print(f"[!] Connection Failed: {e}")
        return

    # Add validity to profiles
    try:
        cur.execute("SELECT validity FROM profiles LIMIT 1")
        print("[OK] Column 'validity' exists in profiles.")
    except:
        print("[*] Adding column 'validity' (INT, Hours) to profiles...")
        cur.execute("ALTER TABLE profiles ADD COLUMN validity INT DEFAULT 24") # Default 24 hours

    conn.commit()
    conn.close()
    print("--- MIGRATION VOUCHER SUCCESS ---")

if __name__ == "__main__":
    migrate()
