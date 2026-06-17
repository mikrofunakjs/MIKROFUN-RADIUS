#!/bin/bash

# MikroFun Radius Installer
# Version: 3.0 (Direct Source)

INSTALL_DIR="/opt/mikrofun"
SERVICE_NAME="mikrofun"

# SIMPAN LOKASI AWAL (sebelum cd kemana-mana)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ORIG_DIR="$(pwd)"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   MikroFun Radius Installer           ${NC}"
echo -e "${BLUE}========================================${NC}"
echo "Source dir : $SCRIPT_DIR"
echo "Run from   : $ORIG_DIR"

# 1. Check Root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Please run as root (sudo bash install.sh)${NC}"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

# 2. Preparation
echo -e "${GREEN}[1/5] Preparing System...${NC}"
apt-get update -qq
# Core dependencies
echo "Installing Core Dependencies..."
apt-get install -y gcc build-essential python3 python3-pip python3-venv python3-dev \
  mysql-client mysql-common mysql-server wireguard wireguard-tools resolvconf php-cli php-curl

# Create Directory
mkdir -p "$INSTALL_DIR"

# 3. Stop Service if running
echo -e "${GREEN}[2/5] Stopping existing services...${NC}"
systemctl stop $SERVICE_NAME 2>/dev/null || true
systemctl stop apache2 2>/dev/null || true
systemctl disable apache2 2>/dev/null || true

# 4. Copy Source Code Langsung dari Folder
echo -e "${GREEN}[3/5] Copying Application Files...${NC}"

# Backup Mikhmon data (kalau ada instalasi lama)
if [ -d "$INSTALL_DIR/mikhmonv3" ]; then
    echo "Backing up Mikhmon data..."
    [ -f "$INSTALL_DIR/mikhmonv3/include/config.php" ] && cp "$INSTALL_DIR/mikhmonv3/include/config.php" "/tmp/mikhmon_config.php.bak"
    [ -d "$INSTALL_DIR/mikhmonv3/img" ] && cp -r "$INSTALL_DIR/mikhmonv3/img" "/tmp/mikhmon_img_bak"
fi

echo "Cleaning old installation..."
find "$INSTALL_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
rm -rf "$INSTALL_DIR/web" "$INSTALL_DIR/wa-service" 2>/dev/null || true

echo "Copying source files from $SCRIPT_DIR to $INSTALL_DIR..."
# Copy semua file penting (skip .git, venv, logs, .license, __pycache__)
for item in "$SCRIPT_DIR"/* "$SCRIPT_DIR"/.[!.]*; do
    base=$(basename "$item")
    case "$base" in
        .git|venv|logs|.license|__pycache__|install.sh) continue ;;
    esac
    if [ -e "$item" ]; then
        cp -r "$item" "$INSTALL_DIR/"
    fi
done

# Kembalikan Mikhmon backup
[ -f "/tmp/mikhmon_config.php.bak" ] && mv "/tmp/mikhmon_config.php.bak" "$INSTALL_DIR/mikhmonv3/include/config.php"
if [ -d "/tmp/mikhmon_img_bak" ]; then
    rm -rf "$INSTALL_DIR/mikhmonv3/img"
    mv "/tmp/mikhmon_img_bak" "$INSTALL_DIR/mikhmonv3/img"
fi

echo "Cleaning Python cache..."
find "$INSTALL_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

cd "$INSTALL_DIR"

echo "Setting up Python Environment..."
# Setup Virtual Environment
python3 -m venv venv || { echo -e "${RED}Failed to create virtual environment!${NC}"; exit 1; }
./venv/bin/pip install --no-cache-dir --upgrade pip || { echo -e "${RED}Failed to upgrade pip!${NC}"; exit 1; }

if [ -f "requirements.txt" ]; then
    echo "Installing Python dependencies (This might take a minute)..."
    ./venv/bin/pip install --no-cache-dir -r requirements.txt || { echo -e "${RED}Failed installing requirements.txt! RAM Full?${NC}"; exit 1; }
    ./venv/bin/pip install --no-cache-dir waitress || exit 1
else
    echo -e "${RED}ERROR: requirements.txt tidak ditemukan!${NC}"
    exit 1
fi

# Verify installation success
if ! ./venv/bin/python -c "import flask" 2>/dev/null; then
    echo -e "${RED}FATAL ERROR: PIP completed but Flask is not installed. Out of Space/RAM?${NC}"
    exit 1
fi

echo "Setting up Schema..."

if [ ! -f "$INSTALL_DIR/database_schema.sql" ]; then
    echo -e "${RED}ERROR: database_schema.sql tidak ditemukan di $INSTALL_DIR!${NC}"
    exit 1
fi

if [ ! -s "database_schema.sql" ]; then
    echo -e "${RED}ERROR: database_schema.sql kosong atau rusak!${NC}"
    exit 1
fi

# 5. Setup Database
echo -e "${GREEN}[4/5] Configuring Database...${NC}"
DB_NAME="radius_db"
DB_USER="radius"
DB_PASS="radiuspass123"

if mysql -e "SHOW DATABASES LIKE '$DB_NAME';" | grep -q "$DB_NAME"; then
    echo -e "${YELLOW}=========================================${NC}"
    echo -e "${YELLOW}WARNING: Existing Database Found!${NC}"
    echo -e "An old MikroFun database was detected on this VPS."
    echo -e "If you are doing a fresh reinstall and want the initial 'Setup Admin' screen,"
    echo -e "you must WIPE the old database now."
    echo -e "${YELLOW}=========================================${NC}"
    read -p "Do you want to completely WIPE the old database? (y/N): " wipe_db
    if [[ "$wipe_db" =~ ^[Yy]$ ]]; then
        echo -e "${RED}Wiping database...${NC}"
        mysql -e "DROP DATABASE $DB_NAME;"
    else
        echo -e "${GREEN}Keeping existing database (Upgrade Mode).${NC}"
    fi
fi

mysql -e "CREATE DATABASE IF NOT EXISTS $DB_NAME;"
mysql -e "CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED WITH mysql_native_password BY '$DB_PASS';" 2>/dev/null || mysql -e "CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASS';"
mysql -e "ALTER USER '$DB_USER'@'localhost' IDENTIFIED WITH mysql_native_password BY '$DB_PASS';" 2>/dev/null || true
mysql -e "GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'localhost';"
mysql -e "FLUSH PRIVILEGES;"

if [ -f "database_schema.sql" ]; then
    echo "Updating Database Schema..."
    mysql -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" < database_schema.sql
fi

# ===== MIGRATION: Add Missing Columns =====
echo "Running Database Migrations..."
mysql -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" <<MIGRATION_SQL
SET @db_name = '$DB_NAME';

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'customers' AND column_name = 'due_date');
SET @query = IF(@col_exists = 0, 'ALTER TABLE customers ADD COLUMN due_date DATE NULL AFTER router_id', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ODP table: rename old columns and add missing ones
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'odps' AND column_name = 'address');
SET @query = IF(@col_exists = 0, 'ALTER TABLE odps ADD COLUMN address VARCHAR(255)', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'odps' AND column_name = 'coordinates');
SET @query = IF(@col_exists = 0, 'ALTER TABLE odps ADD COLUMN coordinates VARCHAR(64)', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'odps' AND column_name = 'capacity');
SET @query = IF(@col_exists = 0, 'ALTER TABLE odps ADD COLUMN capacity INT DEFAULT 8', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Profiles table: add type column if missing (for voucher support)
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'profiles' AND column_name = 'type');
SET @query = IF(@col_exists = 0, "ALTER TABLE profiles ADD COLUMN type ENUM('pppoe','voucher') DEFAULT 'pppoe'", 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- EXPAND PASSWORD LENGTH (VERY IMPORTANT)
ALTER TABLE users MODIFY COLUMN password VARCHAR(255);
ALTER TABLE customers MODIFY COLUMN password VARCHAR(255);

-- Customers table: add mac_address and static_ip if missing
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'customers' AND column_name = 'mac_address');
SET @query = IF(@col_exists = 0, 'ALTER TABLE customers ADD COLUMN mac_address VARCHAR(32) NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'customers' AND column_name = 'static_ip');
SET @query = IF(@col_exists = 0, 'ALTER TABLE customers ADD COLUMN static_ip VARCHAR(32) NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- App Logs table (for web log viewer)
CREATE TABLE IF NOT EXISTS app_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    level VARCHAR(10) NOT NULL DEFAULT 'INFO',
    message VARCHAR(500),
    detail TEXT,
    created_at DATETIME DEFAULT NOW()
);

-- Profiles table: add router_id for per-router/area pricing
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'profiles' AND column_name = 'router_id');
SET @query = IF(@col_exists = 0, 'ALTER TABLE profiles ADD COLUMN router_id INT NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Voucher Batches table (for grouping vouchers)
CREATE TABLE IF NOT EXISTS voucher_batches (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    profile_id INT NULL,
    created_at DATETIME DEFAULT NOW()
);

-- Vouchers: add batch_id column
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'vouchers' AND column_name = 'batch_id');
SET @query = IF(@col_exists = 0, 'ALTER TABLE vouchers ADD COLUMN batch_id INT NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Vouchers: add expires_at column
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'vouchers' AND column_name = 'expires_at');
SET @query = IF(@col_exists = 0, 'ALTER TABLE vouchers ADD COLUMN expires_at DATE NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Vouchers: add activated_at (when voucher was first used)
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'vouchers' AND column_name = 'activated_at');
SET @query = IF(@col_exists = 0, 'ALTER TABLE vouchers ADD COLUMN activated_at DATETIME NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Vouchers: add session_id (RADIUS Acct-Session-Id for CoA disconnect)
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'vouchers' AND column_name = 'session_id');
SET @query = IF(@col_exists = 0, 'ALTER TABLE vouchers ADD COLUMN session_id VARCHAR(128) NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Vouchers: add nas_id (link to routers table for CoA)
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'vouchers' AND column_name = 'nas_id');
SET @query = IF(@col_exists = 0, 'ALTER TABLE vouchers ADD COLUMN nas_id INT NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Vouchers: add buy_price
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'vouchers' AND column_name = 'buy_price');
SET @query = IF(@col_exists = 0, 'ALTER TABLE vouchers ADD COLUMN buy_price DECIMAL(10,2) DEFAULT 0', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Vouchers: add quota_limit
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'vouchers' AND column_name = 'quota_limit');
SET @query = IF(@col_exists = 0, 'ALTER TABLE vouchers ADD COLUMN quota_limit BIGINT DEFAULT 0', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Vouchers: add reseller_id
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'vouchers' AND column_name = 'reseller_id');
SET @query = IF(@col_exists = 0, 'ALTER TABLE vouchers ADD COLUMN reseller_id INT NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Expand payments status ENUM to include processing and failed
ALTER TABLE payments MODIFY COLUMN status ENUM('pending','processing','approved','rejected','failed') DEFAULT 'pending';

-- Customers: add billing_type
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'customers' AND column_name = 'billing_type');
SET @query = IF(@col_exists = 0, "ALTER TABLE customers ADD COLUMN billing_type VARCHAR(20) DEFAULT 'postpaid'", 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Users: add discount_percent
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'users' AND column_name = 'discount_percent');
SET @query = IF(@col_exists = 0, 'ALTER TABLE users ADD COLUMN discount_percent DECIMAL(5,2) DEFAULT 0', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Users: add balance
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'users' AND column_name = 'balance');
SET @query = IF(@col_exists = 0, 'ALTER TABLE users ADD COLUMN balance DECIMAL(15,2) DEFAULT 0', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Payments: add reseller_id
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'payments' AND column_name = 'reseller_id');
SET @query = IF(@col_exists = 0, 'ALTER TABLE payments ADD COLUMN reseller_id INT NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Reseller Transactions table
CREATE TABLE IF NOT EXISTS reseller_transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    reseller_id INT NOT NULL,
    type VARCHAR(32) DEFAULT 'topup',
    amount DECIMAL(15,2) DEFAULT 0,
    description TEXT,
    balance_before DECIMAL(15,2) DEFAULT 0,
    balance_after DECIMAL(15,2) DEFAULT 0,
    created_at DATETIME DEFAULT NOW(),
    FOREIGN KEY (reseller_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ODPs: add odc_id
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'odps' AND column_name = 'odc_id');
SET @query = IF(@col_exists = 0, 'ALTER TABLE odps ADD COLUMN odc_id INT NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Tunnels: add missing columns
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'tunnels' AND column_name = 'mikrotik_user');
SET @query = IF(@col_exists = 0, 'ALTER TABLE tunnels ADD COLUMN mikrotik_user VARCHAR(64) NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'tunnels' AND column_name = 'mikrotik_password');
SET @query = IF(@col_exists = 0, 'ALTER TABLE tunnels ADD COLUMN mikrotik_password VARCHAR(255) NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'tunnels' AND column_name = 'mikrotik_api_port');
SET @query = IF(@col_exists = 0, 'ALTER TABLE tunnels ADD COLUMN mikrotik_api_port INT DEFAULT 8728', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'tunnels' AND column_name = 'public_api_port');
SET @query = IF(@col_exists = 0, 'ALTER TABLE tunnels ADD COLUMN public_api_port INT NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Profiles: add missing columns
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'profiles' AND column_name = 'burst_limit');
SET @query = IF(@col_exists = 0, 'ALTER TABLE profiles ADD COLUMN burst_limit VARCHAR(32) NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'profiles' AND column_name = 'burst_threshold');
SET @query = IF(@col_exists = 0, 'ALTER TABLE profiles ADD COLUMN burst_threshold VARCHAR(32) NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'profiles' AND column_name = 'burst_time');
SET @query = IF(@col_exists = 0, 'ALTER TABLE profiles ADD COLUMN burst_time VARCHAR(32) NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'profiles' AND column_name = 'limit_at');
SET @query = IF(@col_exists = 0, 'ALTER TABLE profiles ADD COLUMN limit_at VARCHAR(32) NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'profiles' AND column_name = 'validity_unit');
SET @query = IF(@col_exists = 0, "ALTER TABLE profiles ADD COLUMN validity_unit ENUM('hours','days','months') DEFAULT 'hours'", 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'profiles' AND column_name = 'shared_users');
SET @query = IF(@col_exists = 0, 'ALTER TABLE profiles ADD COLUMN shared_users INT DEFAULT 1', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'profiles' AND column_name = 'quota_limit');
SET @query = IF(@col_exists = 0, 'ALTER TABLE profiles ADD COLUMN quota_limit VARCHAR(32) NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Routers: add vpn_type and vpn_password
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'routers' AND column_name = 'vpn_type');
SET @query = IF(@col_exists = 0, "ALTER TABLE routers ADD COLUMN vpn_type VARCHAR(32) DEFAULT 'direct_local'", 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = @db_name AND table_name = 'routers' AND column_name = 'vpn_password');
SET @query = IF(@col_exists = 0, 'ALTER TABLE routers ADD COLUMN vpn_password VARCHAR(64) NULL', 'SELECT "Exists"');
PREPARE stmt FROM @query; EXECUTE stmt; DEALLOCATE PREPARE stmt;
MIGRATION_SQL

# 6. Firewall & WireGuard
echo -e "${GREEN}[5/9] Configuring Network & VPN...${NC}"
# Re-ensure wireguard-tools is installed (sometimes it's missed)
if ! command -v wg &> /dev/null; then
    apt-get install -y wireguard-tools
fi

apt-get install -y ufw
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 1812/udp
ufw allow 1813/udp
ufw allow 51820/udp

mkdir -p /etc/wireguard

# Check if keys exist and are valid
PRIVATE_KEY=""
if [ -s /etc/wireguard/privatekey ]; then
    PRIVATE_KEY=$(cat /etc/wireguard/privatekey | tr -d '\n\r ')
fi

# Regenerate if missing or empty
if [ -z "$PRIVATE_KEY" ] || [ ${#PRIVATE_KEY} -lt 40 ]; then
    echo "Generating new Server Keys (Old keys missing or invalid)..."
    rm -f /etc/wireguard/privatekey /etc/wireguard/publickey
    wg genkey | tee /etc/wireguard/privatekey | wg pubkey > /etc/wireguard/publickey
    chmod 600 /etc/wireguard/privatekey
    PRIVATE_KEY=$(cat /etc/wireguard/privatekey | tr -d '\n\r ')
fi

echo "Writing wg0.conf..."
echo "[Interface]" > /etc/wireguard/wg0.conf
echo "Address = 10.66.66.1/24" >> /etc/wireguard/wg0.conf
echo "ListenPort = 51820" >> /etc/wireguard/wg0.conf
echo "PrivateKey = ${PRIVATE_KEY}" >> /etc/wireguard/wg0.conf
echo "SaveConfig = true" >> /etc/wireguard/wg0.conf
chmod 600 /etc/wireguard/wg0.conf

if ! modprobe wireguard >/dev/null 2>&1; then
    echo -e "${BLUE}Notice: Native WireGuard missing. Installing user-space wireguard-go...${NC}"
    apt-get install -y -qq -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" golang
    go install git.zx2c4.com/wireguard-go@latest
    cp ~/go/bin/wireguard-go /usr/local/bin/ || true
    export WG_QUICK_USERSPACE_IMPLEMENTATION=wireguard-go
    export WG_I_PREFER_BUGGY_USERSPACE_TO_POLISHED_KMOD=1
fi

systemctl daemon-reload || true
if command -v wg-quick >/dev/null 2>&1 || [ -f "/usr/bin/wg-quick" ]; then
    systemctl enable wg-quick@wg0 2>/dev/null || true
    systemctl start wg-quick@wg0 2>/dev/null || wg-quick up wg0 || true
else
    echo -e "${BLUE}Warning: wg-quick totally failed.${NC}"
fi

# 7. Multi-VPN Setup (L2TP)
echo -e "${GREEN}[6/9] Configuring Multi-VPN (L2TP)...${NC}"
apt-get purge -y -qq libreswan || true
apt-get install -y -qq -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" strongswan xl2tpd

if [ -f "$INSTALL_DIR/web/vpn_server_setup.py" ]; then
    $INSTALL_DIR/venv/bin/python $INSTALL_DIR/web/vpn_server_setup.py || echo -e "${YELLOW}Warning: Multi-VPN setup encountered issues.${NC}"
fi

# 8. ZeroTier Setup
echo -e "${GREEN}[7/9] Configuring ZeroTier VPN...${NC}"
if ! command -v zerotier-cli &> /dev/null; then
    echo "Installing ZeroTier..."
    # Attempt curl script first
    if curl -s https://install.zerotier.com | bash; then
        echo "ZeroTier installed via script."
    else
        echo "Curl script failed, attempting apt repository method..."
        apt-get install -y -qq gnupg
        curl -s 'https://raw.githubusercontent.com/zerotier/ZeroTierOne/master/doc/contact%40zerotier.com.gpg' | gpg --import
        if [ $? -eq 0 ]; then
            # Detect debian/ubuntu version for repo
            DISTRO=$(lsb_release -cs 2>/dev/null || echo "bookworm")
            echo "deb http://download.zerotier.com/debian/$DISTRO $DISTRO main" > /etc/apt/sources.list.d/zerotier.list
            apt-get update -qq
            apt-get install -y -qq zerotier-one
        fi
    fi
fi

if command -v zerotier-cli &> /dev/null; then
    echo "Starting and enabling ZeroTier service..."
    systemctl enable zerotier-one
    systemctl start zerotier-one
else
    echo -e "${RED}Warning: ZeroTier installation failed. VPN features might not work.${NC}"
fi

# 9. Service Setup
echo -e "${GREEN}[8/9] Starting Service...${NC}"
cat > /etc/systemd/system/$SERVICE_NAME.service <<SYSTEMD_EOF
[Unit]
Description=MikroFun Radius Service
After=network.target mysql.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStartPre=/bin/bash -c "find $INSTALL_DIR -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true"
ExecStart=$INSTALL_DIR/venv/bin/python run_dist.py
Restart=always
Environment="PORT=80"

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF

systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl restart $SERVICE_NAME

# 10. Mikhmon Service Setup
echo -e "${GREEN}[9/9] Configuring Mikhmon Auto-start (Port 8080)...${NC}"
MIKHMON_DIR="$INSTALL_DIR/mikhmonv3"
PHP_BIN=$(which php || echo "/usr/bin/php")

if [ -d "$MIKHMON_DIR" ]; then
    cat > /etc/systemd/system/mikhmon.service <<MIKHMON_EOF
[Unit]
Description=Mikhmon v3 PHP Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$MIKHMON_DIR
ExecStart=$PHP_BIN -S 0.0.0.0:8080 -t $MIKHMON_DIR
Restart=always

[Install]
WantedBy=multi-user.target
MIKHMON_EOF

    systemctl daemon-reload
    systemctl enable mikhmon.service
    systemctl restart mikhmon.service
    echo -e "${GREEN}Mikhmon service is active on port 8080.${NC}"
else
    echo -e "${YELLOW}Warning: Mikhmon folder not found. Skipping service setup.${NC}"
fi

# 11. CLI Shortcut
echo -e "${GREEN}Creating 'mikrofun' CLI Shortcut...${NC}"
cat > /usr/local/bin/mikrofun <<EOF
#!/bin/bash
PROJECT_DIR="/opt/mikrofun"
VENV="\$PROJECT_DIR/venv/bin/python3"

case "\$1" in
    "cd")
        echo "Masuk ke folder project..."
        cd \$PROJECT_DIR && exec bash
        ;;
    "reset")
        echo "Menjalankan Reset Admin..."
        cd \$PROJECT_DIR && \$VENV reset_admin.py
        ;;
    "logs")
        echo "Menampilkan Log Radius..."
        tail -f \$PROJECT_DIR/logs/radius.log
        ;;
    "restart")
        echo "Restart Service MikroFun..."
        systemctl restart mikrofun
        ;;
    "status")
        systemctl status mikrofun
        ;;
    "mikhmon")
        case "$2" in
            "restart") systemctl restart mikhmon ;;
            "status") systemctl status mikhmon ;;
            "stop") systemctl stop mikhmon ;;
            *) echo "Penggunaan: mikrofun mikhmon [restart|status|stop]" ;;
        esac
        ;;
    *)
        echo "Penggunaan: mikrofun [cd|reset|logs|restart|status|mikhmon]"
        ;;
esac
EOF
chmod +x /usr/local/bin/mikrofun

# 8. Node.js & Baileys WA Setup
echo -e "${GREEN}Installing Node.js & Baileys WA Gateway...${NC}"
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y -qq -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" nodejs
npm install -g pm2

cd $INSTALL_DIR/wa-service
npm install

# Restart PM2 gently
pm2 delete "mikrofun-wa" 2>/dev/null || true
pm2 start server.js --name "mikrofun-wa"
pm2 save
env PATH=$PATH:/usr/bin pm2 startup systemd -u root --hp /root 2>/dev/null || true
cd $INSTALL_DIR

# 9. Verification
echo -e "${GREEN}[CHECK] Verifying Deployment...${NC}"
echo "Waiting for services to bind ports (80 & 8080)..."

MIKHMON_READY=false
MIKROFUN_READY=false

for i in {1..20}; do
    if ! $MIKROFUN_READY && ss -tuln | grep -q ":80 "; then
        echo -e "${GREEN}SUCCESS: MikroFun (Port 80) is ONLINE!${NC}"
        MIKROFUN_READY=true
    fi
    
    if ! $MIKHMON_READY && ss -tuln | grep -q ":8080 "; then
        echo -e "${GREEN}SUCCESS: Mikhmon (Port 8080) is ONLINE!${NC}"
        MIKHMON_READY=true
    fi

    if $MIKROFUN_READY && $MIKHMON_READY; then
        # Try to get real public IP
        PUBLIC_IP=$(curl -s https://api.ipify.org || hostname -I | awk '{print $1}')
        echo -e "${BLUE}========================================${NC}"
        echo -e "${GREEN}   INSTALASI SELESAI & SEMUA JALAN!     ${NC}"
        echo -e "${BLUE}========================================${NC}"
        echo -e "Dashboard: http://$PUBLIC_IP"
        echo -e "Mikhmon:   Terintegrasi di dalam Dashboard"
        echo -e "${BLUE}========================================${NC}"
        exit 0
    fi
    
    # Retry starting mikhmon if it's taking too long
    if [ $i -eq 10 ] && ! $MIKHMON_READY; then
        echo -e "${YELLOW}Retrying Mikhmon service...${NC}"
        systemctl restart mikhmon
    fi
    
    sleep 2
done

echo -e "${RED}ERROR: Some services failed to start.${NC}"
echo "Current Ports:"
ss -tuln | grep -E '80|8080'
exit 1
