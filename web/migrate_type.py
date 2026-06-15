#!/usr/bin/env python3
import mysql.connector

# DATABASE CONFIG
DB_HOST = 'localhost'
DB_USER = 'radius'
DB_PASS = 'radiuspass123'
DB_NAME = 'radius_db'

def migrate():
    print("--- MIGRATION PROFILE TYPE START ---")
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

    # Add type to profiles
    try:
        cur.execute("SELECT type FROM profiles LIMIT 1")
        print("[OK] Column 'type' exists in profiles.")
    except:
        print("[*] Adding column 'type' (ENUM pppoe/voucher) to profiles...")
        cur.execute("ALTER TABLE profiles ADD COLUMN type ENUM('pppoe', 'voucher') DEFAULT 'pppoe'")
        
        # Optional: attempt to guess type based on validity?
        # If validity > 0 AND validity != 720 (30 days/1 month standard pppoe), maybe valid?
        # Let's just leave it as pppoe for safety user can edit.

    conn.commit()
    conn.close()
    print("--- MIGRATION PROFILE TYPE SUCCESS ---")

if __name__ == "__main__":
    migrate()
