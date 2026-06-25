import os
import mysql.connector
from mysql.connector import Error, pooling

"""
Database Helper
"""

try:
    from web.config import DB_CONFIG, DB_ERROR_LOG_PATH
except ImportError:
    # Fallback for scripts running from root
    from config import DB_CONFIG, DB_ERROR_LOG_PATH

# --- CONNECTION POOLING (SAT-SET) ---
_DB_POOL = None

def get_db():
    global _DB_POOL
    try:
        if _DB_POOL is None:
            # Create pool once
            _DB_POOL = pooling.MySQLConnectionPool(
                pool_name="mikrofun_pool",
                pool_size=5, # Kurangi load MySQL (hemat memory)
                pool_reset_session=True,
                **DB_CONFIG
            )
        return _DB_POOL.get_connection()
    except Error as e:
        print(f"DB error (Pooling): {e}")
        # Fallback to direct connection if pool fails
        try:
            return mysql.connector.connect(**DB_CONFIG)
        except:
            return None

def ensure_schema_updates():
    try:
        conn = get_db()
        if not conn: return
        cur = conn.cursor()
        
        # Check and add columns to payments table
        cur.execute("SHOW COLUMNS FROM payments LIKE 'payment_type'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE payments ADD COLUMN payment_type VARCHAR(32) DEFAULT 'bill'")
            
        cur.execute("SHOW COLUMNS FROM payments LIKE 'voucher_code'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE payments ADD COLUMN voucher_code VARCHAR(32)")
            
            
        cur.execute("SHOW COLUMNS FROM payments LIKE 'profile_id'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE payments ADD COLUMN profile_id INT")
            
        cur.execute("SHOW COLUMNS FROM payments LIKE 'guest_email'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE payments MODIFY customer_id INT NULL")
            cur.execute("ALTER TABLE payments DROP FOREIGN KEY payments_ibfk_1")
            cur.execute("ALTER TABLE payments ADD FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL")
            cur.execute("ALTER TABLE payments ADD COLUMN guest_email VARCHAR(128) NULL")
            cur.execute("ALTER TABLE payments ADD COLUMN guest_phone VARCHAR(32) NULL")
            
        cur.execute("SHOW COLUMNS FROM payments LIKE 'reseller_id'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE payments ADD COLUMN reseller_id INT NULL")
            cur.execute("ALTER TABLE payments ADD FOREIGN KEY (reseller_id) REFERENCES users(id) ON DELETE SET NULL")
            
        # Telegram Integration
        cur.execute("SHOW COLUMNS FROM settings LIKE 'telegram_bot_token'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE settings ADD COLUMN telegram_bot_token VARCHAR(255) DEFAULT ''")
            
        cur.execute("SHOW COLUMNS FROM settings LIKE 'telegram_chat_id'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE settings ADD COLUMN telegram_chat_id VARCHAR(128) DEFAULT ''")
            
        # DHCP MAC-Auth & Static IP
        cur.execute("SHOW COLUMNS FROM customers LIKE 'mac_address'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE customers ADD COLUMN mac_address VARCHAR(32) NULL")
            
        cur.execute("SHOW COLUMNS FROM customers LIKE 'static_ip'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE customers ADD COLUMN static_ip VARCHAR(32) NULL")
            
        # Active Sessions Columns
        cur.execute("SHOW COLUMNS FROM active_sessions LIKE 'mac_address'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE active_sessions ADD COLUMN mac_address VARCHAR(32) NULL AFTER nas_ip")
            print("Added 'mac_address' to active_sessions")

        # Assets Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS assets (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                category VARCHAR(64) DEFAULT 'modem',
                brand VARCHAR(64),
                mac_address VARCHAR(32),
                serial_number VARCHAR(64),
                purchase_price DECIMAL(15,2) DEFAULT 0,
                purchase_date DATE,
                status VARCHAR(32) DEFAULT 'available',
                assigned_to_type VARCHAR(32),
                assigned_to_id INT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uk_serial (serial_number)
            )
        """)

        # Migration: add UNIQUE on serial_number for existing tables
        cur.execute("""
            SELECT COUNT(*) INTO @sn_exists FROM information_schema.STATISTICS
            WHERE table_schema = DATABASE() AND table_name = 'assets' AND index_name = 'uk_serial'
        """)
        cur.execute("SELECT @sn_exists")
        if cur.fetchone()['@sn_exists'] == 0:
            try:
                cur.execute("ALTER TABLE assets ADD UNIQUE KEY uk_serial (serial_number)")
            except Exception:
                pass

        cur.execute("""
            CREATE TABLE IF NOT EXISTS asset_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                asset_id INT NULL,
                action VARCHAR(64),
                entity_type VARCHAR(32),
                entity_id INT,
                admin_id INT,
                action_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE SET NULL
            )
        """)

        # Migration: fix FK to ON DELETE SET NULL for existing installs
        try:
            cur.execute("ALTER TABLE asset_logs MODIFY asset_id INT NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE asset_logs DROP FOREIGN KEY asset_logs_ibfk_1")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE asset_logs ADD FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE SET NULL")
        except Exception:
            pass

        # Helpdesk Tickets
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INT AUTO_INCREMENT PRIMARY KEY,
                customer_id INT NOT NULL,
                subject VARCHAR(200) NOT NULL,
                category VARCHAR(64) DEFAULT 'General',
                priority ENUM('low','medium','high') DEFAULT 'medium',
                status ENUM('open','answered','closed') DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_replies (
                id INT AUTO_INCREMENT PRIMARY KEY,
                ticket_id INT NOT NULL,
                sender_type ENUM('client','admin') NOT NULL,
                sender_id INT NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
            )
        """)

        # 2. ODC & ODP Link
        cur.execute("""
            CREATE TABLE IF NOT EXISTS odcs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(64) UNIQUE NOT NULL,
                address VARCHAR(255),
                coordinates VARCHAR(64),
                capacity INT DEFAULT 12,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("SHOW COLUMNS FROM odps LIKE 'odc_id'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE odps ADD COLUMN odc_id INT NULL")
            
        # 3. Billing Type for Customers
        cur.execute("SHOW COLUMNS FROM customers LIKE 'billing_type'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE customers ADD COLUMN billing_type ENUM('prepaid', 'postpaid') DEFAULT 'prepaid'")

        # 4. ACS Tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS acs_devices (
                id INT AUTO_INCREMENT PRIMARY KEY,
                customer_id INT NULL,
                serial_number VARCHAR(64) UNIQUE NOT NULL,
                oui VARCHAR(16),
                model VARCHAR(64),
                vendor VARCHAR(64),
                firmware VARCHAR(64),
                ip_address VARCHAR(64),
                ssid_24 VARCHAR(64),
                ssid_50 VARCHAR(64),
                last_inform DATETIME,
                created_at DATETIME DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS acs_tasks (
                id INT AUTO_INCREMENT PRIMARY KEY,
                device_serial VARCHAR(64) NOT NULL,
                task_type VARCHAR(32) NOT NULL,
                value TEXT,
                param_path VARCHAR(255),
                status ENUM('pending','sent','done','failed') DEFAULT 'pending',
                created_at DATETIME DEFAULT NOW(),
                executed_at DATETIME NULL
            )
        """)
        
        # 3. Voucher Batches
        cur.execute("""
            CREATE TABLE IF NOT EXISTS voucher_batches (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                profile_id INT NULL,
                created_at DATETIME DEFAULT NOW()
            )
        """)
        
        # 4. Vouchers Columns
        cur.execute("SHOW COLUMNS FROM vouchers LIKE 'batch_id'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE vouchers ADD COLUMN batch_id INT NULL")
            
        cur.execute("SHOW COLUMNS FROM vouchers LIKE 'expires_at'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE vouchers ADD COLUMN expires_at DATE NULL")
            
        cur.execute("SHOW COLUMNS FROM vouchers LIKE 'activated_at'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE vouchers ADD COLUMN activated_at DATETIME NULL")
            
        cur.execute("SHOW COLUMNS FROM vouchers LIKE 'session_id'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE vouchers ADD COLUMN session_id VARCHAR(128) NULL")
            
        cur.execute("SHOW COLUMNS FROM vouchers LIKE 'nas_id'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE vouchers ADD COLUMN nas_id INT NULL")

        # 5. RESELLER SYSTEM (MITRA)
        cur.execute("SHOW COLUMNS FROM users LIKE 'balance'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE users ADD COLUMN balance DECIMAL(15,2) DEFAULT 0")

        cur.execute("SHOW COLUMNS FROM users LIKE 'discount_percent'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE users ADD COLUMN discount_percent INT DEFAULT 0")

        cur.execute("SHOW COLUMNS FROM vouchers LIKE 'reseller_id'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE vouchers ADD COLUMN reseller_id INT NULL")
            cur.execute("ALTER TABLE vouchers ADD COLUMN buy_price DECIMAL(10,2) DEFAULT 0")

        # 6. QUOTA SYSTEM
        cur.execute("SHOW COLUMNS FROM profiles LIKE 'quota_limit'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE profiles ADD COLUMN quota_limit BIGINT DEFAULT 0")
            print("Added 'quota_limit' to profiles")

        # MULTI-USER, BURST, POOL & ROUTER MIGRATE
        for col, defn in [
            ('shared_users', 'INT DEFAULT 1'),
            ('burst_limit', 'VARCHAR(32) NULL'),
            ('burst_threshold', 'VARCHAR(32) NULL'),
            ('burst_time', 'VARCHAR(16) NULL'),
            ('limit_at', 'VARCHAR(32) NULL'),
            ('pool_name', 'VARCHAR(64) NULL'),
            ('router_id', 'INT NULL'),
            ('validity_unit', "VARCHAR(16) DEFAULT 'hours'"),
            ('description', 'TEXT NULL'),
            ('type', "VARCHAR(16) DEFAULT 'pppoe'")
        ]:
            cur.execute(f"SHOW COLUMNS FROM profiles LIKE '{col}'")
            if not cur.fetchone():
                cur.execute(f"ALTER TABLE profiles ADD COLUMN {col} {defn}")
                print(f"Added '{col}' to profiles")

        cur.execute("SHOW COLUMNS FROM vouchers LIKE 'quota_limit'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE vouchers ADD COLUMN quota_limit BIGINT DEFAULT 0")
            print("Added 'quota_limit' to vouchers")

        cur.execute("SHOW COLUMNS FROM vouchers LIKE 'quota_used'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE vouchers ADD COLUMN quota_used BIGINT DEFAULT 0")
            print("Added 'quota_used' to vouchers")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS reseller_transactions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                reseller_id INT NOT NULL,
                type ENUM('topup', 'purchase') NOT NULL,
                amount DECIMAL(15,2) NOT NULL,
                description VARCHAR(255),
                balance_before DECIMAL(15,2) NOT NULL,
                balance_after DECIMAL(15,2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (reseller_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS income_ledger (
                id           INT AUTO_INCREMENT PRIMARY KEY,
                source_type  ENUM('admin_voucher','mitra_voucher','client_payment','mitra_deposit') NOT NULL,
                source_id    INT DEFAULT NULL,
                ref_number   VARCHAR(100) DEFAULT NULL,
                description  VARCHAR(255) NOT NULL,
                gross_amount DECIMAL(15,2) NOT NULL DEFAULT 0,
                cost_amount  DECIMAL(15,2) NOT NULL DEFAULT 0,
                net_profit   DECIMAL(15,2) NOT NULL DEFAULT 0,
                party_name   VARCHAR(100) DEFAULT NULL,
                category     ENUM('voucher','subscription','deposit') NOT NULL,
                recorded_by  VARCHAR(100) DEFAULT 'system',
                created_at   DATETIME DEFAULT NOW(),
                INDEX idx_source_type (source_type),
                INDEX idx_created_at  (created_at),
                INDEX idx_category    (category)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS wa_templates (
                id INT AUTO_INCREMENT PRIMARY KEY,
                template_key VARCHAR(64) UNIQUE NOT NULL,
                message_text TEXT NOT NULL,
                placeholders VARCHAR(255)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS wa_reminders_sent (
                id INT AUTO_INCREMENT PRIMARY KEY,
                customer_id INT NOT NULL,
                due_date DATE NOT NULL,
                sent_at DATETIME DEFAULT NOW(),
                UNIQUE KEY uk_customer_due (customer_id, due_date)
            )
        """)
        
        # Seed Defaults for WA
        defaults = [
            ('voucher_purchase', 'Pembayaran berhasil! Kode Voucher Hotspot Anda: *{code}*\nPaket: {profile_name}\nSilakan gunakan kode ini untuk login Wi-Fi.', '{code}, {profile_name}'),
            ('bill_payment', 'Pembayaran diterima! Layanan Internet Anda telah aktif hingga {due_date}. Terima kasih.', '{due_date}'),
            ('isolir_warning', 'Halo {name}, layanan internet Anda akan segera habis pada {due_date}. Segera lakukan pembayaran untuk menghindari pemutusan.', '{name}, {due_date}')
        ]
        
        for key, text, placeholders in defaults:
            cur.execute("""
                INSERT IGNORE INTO wa_templates (template_key, message_text, placeholders)
                VALUES (%s, %s, %s)
            """, (key, text, placeholders))

        # --- White Label Settings ---
        cur.execute("INSERT IGNORE INTO settings (setting_key, setting_value) VALUES ('company_name', 'MikroFun')")

        # OLT Management
        cur.execute("""
            CREATE TABLE IF NOT EXISTS olts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                brand VARCHAR(64),
                model VARCHAR(64),
                ip_address VARCHAR(32),
                api_port INT DEFAULT 8728,
                username VARCHAR(64),
                password VARCHAR(64),
                total_ports INT DEFAULT 8,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Link ODC to OLT (optional)
        cur.execute("SHOW COLUMNS FROM odcs LIKE 'olt_id'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE odcs ADD COLUMN olt_id INT NULL")
            cur.execute("ALTER TABLE odcs ADD FOREIGN KEY (olt_id) REFERENCES olts(id) ON DELETE SET NULL")

        # MikroTunnel - VPN NAT Traversal
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tunnels (
                id INT AUTO_INCREMENT PRIMARY KEY,
                tunnel_name VARCHAR(128) NOT NULL,
                vpn_username VARCHAR(64) UNIQUE,
                vpn_password VARCHAR(64),
                internal_ip VARCHAR(15),
                mikrotik_winbox_port INT DEFAULT 8291,
                mikrotik_web_port INT DEFAULT 80,
                public_winbox_port INT,
                public_web_port INT,
                is_active BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migration: add new columns if table already exists from old schema
        for col, defn in [
            ('tunnel_name', "VARCHAR(128) DEFAULT 'Unnamed'"),
            ('mikrotik_winbox_port', 'INT DEFAULT 8291'),
            ('mikrotik_web_port', 'INT DEFAULT 80'),
            ('mikrotik_api_port', 'INT DEFAULT 8728'),
            ('public_api_port', 'INT DEFAULT NULL'),
            ('mikrotik_user', "VARCHAR(64) DEFAULT 'admin'"),
            ('mikrotik_password', "VARCHAR(64) DEFAULT ''")
        ]:
            try:
                cur.execute(f"SHOW COLUMNS FROM tunnels LIKE '{col}'")
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE tunnels ADD COLUMN {col} {defn}")
            except:
                pass
        # Drop router_id FK if exists (old schema)
        try:
            cur.execute("SHOW COLUMNS FROM tunnels LIKE 'router_id'")
            if cur.fetchone():
                try:
                    cur.execute("ALTER TABLE tunnels DROP FOREIGN KEY tunnels_ibfk_1")
                except:
                    pass
                cur.execute("ALTER TABLE tunnels MODIFY COLUMN router_id INT NULL")
        except:
            pass

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Schema migration error: {e}")
        
    # Check if routers missing vpn_type
    try:
        conn = get_db()
        if not conn:
            return
        cur = conn.cursor(dictionary=True)
        
        # Router VPN Type Migration
        cur.execute("SHOW COLUMNS FROM routers LIKE 'vpn_type'")
        row = cur.fetchone()
        if not row:
            cur.execute("ALTER TABLE routers ADD COLUMN vpn_type ENUM('wireguard', 'l2tp', 'sstp', 'direct_local', 'public_ip', 'zerotier') DEFAULT 'wireguard'")
            cur.execute("ALTER TABLE routers ADD COLUMN vpn_password VARCHAR(100) DEFAULT NULL")
            print("Added 'vpn_type' and 'vpn_password' to routers")
        else:
            cur.execute("ALTER TABLE routers MODIFY COLUMN vpn_type ENUM('wireguard', 'l2tp', 'sstp', 'direct_local', 'public_ip', 'zerotier') DEFAULT 'wireguard'")
            print("Updated 'vpn_type' ENUM in routers")

        # Migration: Add ip_address to routers
        cur.execute("SHOW COLUMNS FROM routers LIKE 'ip_address'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE routers ADD COLUMN ip_address VARCHAR(32) NULL AFTER name")
            print("Added 'ip_address' to routers")

        # Profiles Burst QoS Migration
        burst_cols = [
            ('burst_limit', 'VARCHAR(32) DEFAULT NULL'),
            ('burst_threshold', 'VARCHAR(32) DEFAULT NULL'),
            ('burst_time', 'VARCHAR(32) DEFAULT NULL'),
            ('limit_at', 'VARCHAR(32) DEFAULT NULL')
        ]
        
        for col_name, col_def in burst_cols:
            cur.execute(f"SHOW COLUMNS FROM profiles LIKE '{col_name}'")
            if not cur.fetchone():
                cur.execute(f"ALTER TABLE profiles ADD COLUMN {col_name} {col_def}")
                print(f"Added '{col_name}' to profiles")

        # Voucher Validity Unit Migration
        cur.execute("SHOW COLUMNS FROM profiles LIKE 'validity_unit'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE profiles ADD COLUMN validity_unit ENUM('hours', 'days', 'months') DEFAULT 'hours'")
            print("Added 'validity_unit' to profiles")

        # PPN / Tax columns
        cur.execute("SHOW COLUMNS FROM profiles LIKE 'tax_percent'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE profiles ADD COLUMN tax_percent DECIMAL(5,2) DEFAULT 0")
            print("Added 'tax_percent' to profiles")

        cur.execute("SHOW COLUMNS FROM income_ledger LIKE 'tax_amount'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE income_ledger ADD COLUMN tax_amount DECIMAL(15,2) DEFAULT 0")
            print("Added 'tax_amount' to income_ledger")

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error migrating database columns: {e}")

def migrate_historical_ledger():
    """
    Migrasi data keuangan historis ke income_ledger.
    Berjalan otomatis saat app startup, aman dijalankan berulang (duplikat di-skip).
    """
    try:
        conn = get_db()
        if not conn:
            return
        cur = conn.cursor(dictionary=True)

        def already_exists(src_type, src_id):
            cur.execute(
                "SELECT id FROM income_ledger WHERE source_type=%s AND source_id=%s LIMIT 1",
                (src_type, src_id)
            )
            return cur.fetchone() is not None

        migrated = 0

        # â”€â”€ 1. Tagihan Pelanggan (payments approved) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        cur.execute("""
            SELECT p.id, p.amount, p.sender_bank, p.payment_date,
                   c.name as cname
            FROM payments p
            LEFT JOIN customers c ON p.customer_id = c.id
            WHERE p.status IN ('approved','paid','settlement') AND p.amount > 0
        """)
        for r in cur.fetchall():
            if already_exists('client_payment', r['id']):
                continue
            amt = float(r['amount'])
            ch  = r.get('sender_bank') or 'Manual'
            cur.execute(
                "INSERT INTO income_ledger (source_type,source_id,ref_number,description,"
                "gross_amount,cost_amount,net_profit,party_name,category,recorded_by,created_at) "
                "VALUES ('client_payment',%s,%s,%s,%s,0,%s,%s,'subscription','migrate',%s)",
                (r['id'], str(r['id']),
                 f"[Historis] Tagihan [{r.get('cname') or '-'}] â€” {ch}",
                 amt, amt, r.get('cname') or '-', r.get('payment_date'))
            )
            migrated += 1

        # â”€â”€ 2. Deposit Mitra (reseller_transactions topup) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        cur.execute("""
            SELECT rt.id, rt.reseller_id, rt.amount, rt.description, rt.created_at,
                   u.username as rname
            FROM reseller_transactions rt
            LEFT JOIN users u ON rt.reseller_id = u.id
            WHERE rt.type='topup' AND rt.amount > 0
        """)
        for r in cur.fetchall():
            if already_exists('mitra_deposit', r['id']):
                continue
            amt  = float(r['amount'])
            name = r.get('rname') or f"ID-{r['reseller_id']}"
            cur.execute(
                "INSERT INTO income_ledger (source_type,source_id,ref_number,description,"
                "gross_amount,cost_amount,net_profit,party_name,category,recorded_by,created_at) "
                "VALUES ('mitra_deposit',%s,%s,%s,%s,0,%s,%s,'deposit','migrate',%s)",
                (r['id'], f"TOPUP-{r['reseller_id']}",
                 f"[Historis] Deposit Mitra [{name}] â€” {r.get('description') or '-'}",
                 amt, amt, name, r.get('created_at'))
            )
            migrated += 1

        # â”€â”€ 3. Pembelian Voucher Mitra (reseller_transactions purchase) â”€â”€â”€
        cur.execute("""
            SELECT rt.id, rt.reseller_id, rt.amount, rt.description, rt.created_at,
                   u.username as rname
            FROM reseller_transactions rt
            LEFT JOIN users u ON rt.reseller_id = u.id
            WHERE rt.type='purchase' AND rt.amount > 0
        """)
        for r in cur.fetchall():
            if already_exists('mitra_voucher', r['id']):
                continue
            cost = float(r['amount'])
            name = r.get('rname') or f"ID-{r['reseller_id']}"
            cur.execute(
                "INSERT INTO income_ledger (source_type,source_id,ref_number,description,"
                "gross_amount,cost_amount,net_profit,party_name,category,recorded_by,created_at) "
                "VALUES ('mitra_voucher',%s,%s,%s,%s,%s,%s,%s,'voucher','migrate',%s)",
                (r['id'], f"MITRA-{r['id']}",
                 f"[Historis] Mitra [{name}] beli Voucher â€” {r.get('description') or '-'}",
                 cost, cost, 0, name, r.get('created_at'))
            )
            migrated += 1

        # â”€â”€ 4. Voucher Admin (dikelompok per batch/hari/profil) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        cur.execute("""
            SELECT COALESCE(v.batch_id, 0) as bid, v.profile_id,
                   DATE(v.created_at) as cdate,
                   p.name as pname, p.price,
                   COUNT(*) as qty, MAX(v.created_at) as cat
            FROM vouchers v
            LEFT JOIN profiles p ON v.profile_id = p.id
            WHERE v.created_by='admin' AND (v.reseller_id IS NULL OR v.reseller_id=0)
            GROUP BY COALESCE(v.batch_id,0), v.profile_id, DATE(v.created_at)
        """)
        for r in cur.fetchall():
            qty   = int(r['qty'] or 0)
            price = float(r['price'] or 0)
            if qty <= 0:
                continue
            # synthetic unique id from batch+profile+date
            import hashlib
            key = f"AV-{r['bid']}-{r['profile_id']}-{r['cdate']}"
            syn_id = int(hashlib.md5(key.encode()).hexdigest()[:7], 16) % 100_000_000
            if already_exists('admin_voucher', syn_id):
                continue
            gross = round(price * qty, 2)
            cur.execute(
                "INSERT INTO income_ledger (source_type,source_id,ref_number,description,"
                "gross_amount,cost_amount,net_profit,party_name,category,recorded_by,created_at) "
                "VALUES ('admin_voucher',%s,%s,%s,%s,0,%s,'Admin ISP','voucher','migrate',%s)",
                (syn_id, key,
                 f"[Historis] Admin Generate {qty}Ã— [{r.get('pname') or '-'}] @ Rp {price:,.0f}",
                 gross, gross, r.get('cat'))
            )
            migrated += 1

        conn.commit()
        cur.close()
        conn.close()
        if migrated > 0:
            print(f"[income_ledger] Migrasi historis selesai: {migrated} record.")
    except Exception as e:
        print(f"[income_ledger] Migrasi historis error (tidak fatal): {e}")


def execute_query(query, params=None, fetch=False, fetch_one=False):
    conn = get_db()
    if not conn:
        return [] if fetch else (None if not fetch_one else {})
    try:
        cur = conn.cursor(dictionary=True, buffered=True)
        cur.execute(query, params or ())
        if fetch_one:
            result = cur.fetchone()
        elif fetch:
            result = cur.fetchall()
        else:
            conn.commit()
            q_upper = query.strip().upper()
            if q_upper.startswith('INSERT'):
                result = cur.lastrowid if cur.lastrowid else None
            else:
                result = cur.rowcount
        cur.close()
        conn.close()
        return result
    except Error as e:
        err_msg = f"Query error: {e}\n  SQL: {query}\n  Params: {params}"
        print(err_msg)
        try:
            with open(DB_ERROR_LOG_PATH, "a") as f:
                f.write(err_msg + "\n---\n")
        except:
            pass
        
        try:
            if conn and conn.is_connected():
                try:
                    conn.rollback()
                except:
                    pass
                try:
                    conn.consume_results()
                except:
                    pass
                conn.close()
        except:
            pass
        return [] if fetch else (None if not fetch_one else {})

def add_performance_indexes():
    """Menambahkan index pada tabel-tabel utama agar pencarian data 'sat-set'."""
    try:
        conn = get_db()
        if not conn: return
        cur = conn.cursor()
        
        # Index untuk radacct 
        for idx_name, table, col in [
            ('idx_radacct_username', 'radacct', 'username'),
            ('idx_radacct_acctstoptime', 'radacct', 'acctstoptime'),
            ('idx_radacct_nasip', 'radacct', 'nasipaddress'),
            ('idx_customers_status', 'customers', 'status'),
            ('idx_vouchers_status', 'vouchers', 'status')
        ]:
            try:
                cur.execute(f"CREATE INDEX {idx_name} ON {table}({col})")
            except: pass

        # Expand payments status ENUM to include processing and failed
        try:
            cur.execute("ALTER TABLE payments MODIFY COLUMN status ENUM('pending','processing','approved','rejected','failed') DEFAULT 'pending'")
        except Exception:
            pass

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Index optimization error: {e}")

# Run schema migrations once on load
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not os.environ.get('FLASK_RUN_FROM_CLI'):
    ensure_schema_updates()
    add_performance_indexes()
    
    # Optimize: Only migrate once to keep startup 'sat-set'
    check_done = execute_query("SELECT setting_value FROM settings WHERE setting_key='migrate_historical_done'", fetch_one=True)
    if not check_done or check_done['setting_value'] != 'true':
        migrate_historical_ledger()
        execute_query("INSERT INTO settings (setting_key, setting_value) VALUES ('migrate_historical_done', 'true') ON DUPLICATE KEY UPDATE setting_value='true'")

