-- =============================================
-- MikroFun Database Schema
-- =============================================

CREATE DATABASE IF NOT EXISTS radius_db;
USE radius_db;

-- Admin Login
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'admin',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Speed Profiles
CREATE TABLE IF NOT EXISTS profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(64) UNIQUE NOT NULL,
    rate_limit VARCHAR(32),
    pool_name VARCHAR(32),
    price DECIMAL(10,2) DEFAULT 0,
    validity INT DEFAULT 0, -- Duration in HOURS
    type ENUM('pppoe', 'voucher') DEFAULT 'pppoe',
    description TEXT,
    router_id INT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Mikrotik Routers
CREATE TABLE IF NOT EXISTS routers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(64),
    vpn_ip VARCHAR(32),
    vpn_public_key VARCHAR(64),
    vpn_private_key VARCHAR(64),
    api_user VARCHAR(64),
    api_password VARCHAR(64),
    api_port INT DEFAULT 8728,
    status VARCHAR(20) DEFAULT 'offline',
    last_seen TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- PPPoE Customers
CREATE TABLE IF NOT EXISTS customers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(64),
    phone VARCHAR(20),
    email VARCHAR(128), -- Added for Payment Gateway
    address TEXT,
    username VARCHAR(64) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    status ENUM('active','expired','disabled','isolir') DEFAULT 'active',
    service_type VARCHAR(20) DEFAULT 'pppoe',
    profile_id INT,
    router_id INT,
    due_date DATE NULL,
    odp_id INT NULL,
    port_number VARCHAR(32) NULL,
    coordinates VARCHAR(128) NULL,
    mac_address VARCHAR(32) NULL,
    static_ip VARCHAR(32) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Hotspot Vouchers
CREATE TABLE IF NOT EXISTS vouchers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(32) UNIQUE NOT NULL,
    profile_id INT,
    duration_hours INT DEFAULT 24,
    price DECIMAL(10,2) DEFAULT 0,
    status ENUM('unused','active','expired') DEFAULT 'unused',
    created_by VARCHAR(64),
    activated_by VARCHAR(64),
    activated_at TIMESTAMP NULL,
    expires_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Active Sessions (for concurrency & disconnect)
CREATE TABLE IF NOT EXISTS active_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    nas_ip VARCHAR(32) NOT NULL,
    mac_address VARCHAR(32) NULL,
    acct_session_id VARCHAR(64),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY (username, acct_session_id)
);

-- Notifications
CREATE TABLE IF NOT EXISTS notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(128) NOT NULL,
    message TEXT,
    category VARCHAR(20) DEFAULT 'info',
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ODPs (Optical Distribution Points)
CREATE TABLE IF NOT EXISTS odps (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(64) UNIQUE NOT NULL,
    address VARCHAR(255),
    coordinates VARCHAR(64),
    capacity INT DEFAULT 8,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Settings (License, etc)
CREATE TABLE IF NOT EXISTS settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    setting_key VARCHAR(64) UNIQUE NOT NULL,
    setting_value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Bank Accounts for Billing
CREATE TABLE IF NOT EXISTS bank_accounts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    bank_name VARCHAR(64) NOT NULL,
    account_number VARCHAR(64) NOT NULL,
    account_holder VARCHAR(128) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Payment History
CREATE TABLE IF NOT EXISTS payments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NULL, -- Can be NULL for public voucher purchases
    guest_email VARCHAR(128) NULL,
    guest_phone VARCHAR(32) NULL,
    amount DECIMAL(15,2) NOT NULL,
    payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status ENUM('pending', 'processing', 'approved', 'rejected', 'failed') DEFAULT 'pending',
    sender_bank VARCHAR(64),
    sender_name VARCHAR(128),
    bank_account_id INT,
    proof_image VARCHAR(255),
    external_ref VARCHAR(64), -- Tripay/Midtrans Reference
    checkout_url TEXT, -- Tripay Checkout URL
    payment_channel VARCHAR(32), -- e.g. BRIVA, QRIS
    payment_type VARCHAR(32) DEFAULT 'bill', -- bill, voucher
    profile_id INT NULL, -- if buying voucher
    voucher_code VARCHAR(32) NULL, -- Issued code
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL
);

-- Helpdesk Tickets
CREATE TABLE IF NOT EXISTS tickets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    subject VARCHAR(200) NOT NULL,
    category VARCHAR(64) DEFAULT 'General',
    priority ENUM('low', 'medium', 'high') DEFAULT 'medium',
    status ENUM('open', 'answered', 'closed') DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

-- Ticket Replies
CREATE TABLE IF NOT EXISTS ticket_replies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ticket_id INT NOT NULL,
    sender_type ENUM('client', 'admin') NOT NULL,
    sender_id INT NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
);

-- Note: Admin user creation is now handled by the Web UI's /setup route on first launch

-- RADIUS Accounting (Standard Schema)
CREATE TABLE IF NOT EXISTS radacct (
    radacctid BIGINT(21) NOT NULL AUTO_INCREMENT,
    acctsessionid VARCHAR(64) DEFAULT '',
    acctuniqueid VARCHAR(32) DEFAULT '',
    username VARCHAR(64) DEFAULT '',
    realm VARCHAR(64) DEFAULT '',
    nasipaddress VARCHAR(15) DEFAULT '',
    nasportid VARCHAR(15) DEFAULT NULL,
    nasporttype VARCHAR(32) DEFAULT NULL,
    acctstarttime DATETIME DEFAULT NULL,
    acctupdatetime DATETIME DEFAULT NULL,
    acctstoptime DATETIME DEFAULT NULL,
    acctinterval INT(12) DEFAULT NULL,
    acctsessiontime INT(12) UNSIGNED DEFAULT NULL,
    acctauthentic VARCHAR(32) DEFAULT NULL,
    connectinfo_start VARCHAR(50) DEFAULT NULL,
    connectinfo_stop VARCHAR(50) DEFAULT NULL,
    acctinputoctets BIGINT(20) DEFAULT NULL,
    acctoutputoctets BIGINT(20) DEFAULT NULL,
    calledstationid VARCHAR(50) DEFAULT '',
    callingstationid VARCHAR(50) DEFAULT '',
    acctterminatecause VARCHAR(32) DEFAULT '',
    servicetype VARCHAR(32) DEFAULT NULL,
    framedprotocol VARCHAR(32) DEFAULT NULL,
    framedipaddress VARCHAR(15) DEFAULT '',
    PRIMARY KEY (radacctid),
    KEY username (username),
    KEY framedipaddress (framedipaddress),
    KEY acctsessionid (acctsessionid),
    KEY acctsessiontime (acctsessiontime),
    KEY acctstarttime (acctstarttime),
    KEY acctstoptime (acctstoptime),
    KEY nasipaddress (nasipaddress)
) ENGINE=InnoDB;
-- =============================================
-- MikroFun Technician Jobs Schema
-- =============================================

USE radius_db;

CREATE TABLE IF NOT EXISTS technician_jobs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ticket_id INT NULL, -- Optional mapping to Helpdesk Tickets
    customer_id INT NULL, -- If related to a specific customer
    technician_id INT NULL, -- Assigned technician (users table)
    job_type VARCHAR(64) NOT NULL, -- 'installation', 'repair', 'maintenance', 'survey'
    title VARCHAR(128) NOT NULL,
    description TEXT,
    priority ENUM('low', 'medium', 'high', 'urgent') DEFAULT 'medium',
    status ENUM('pending', 'on_way', 'working', 'resolved', 'cancelled') DEFAULT 'pending',
    scheduled_date DATETIME NULL,
    completed_at DATETIME NULL,
    evidence_photo_1 VARCHAR(255) NULL, -- Redaman / Router photo
    evidence_photo_2 VARCHAR(255) NULL, -- Location / ODP photo
    resolution_notes TEXT,
    created_by INT NULL, -- Admin who created this job
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (technician_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL
);

-- =============================================
-- MikroTunnel (VPN NAT Traversal) Schema
-- =============================================
CREATE TABLE IF NOT EXISTS `tunnels` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `tunnel_name` varchar(128) NOT NULL,
  `vpn_username` varchar(64) DEFAULT NULL,
  `vpn_password` varchar(64) DEFAULT NULL,
  `internal_ip` varchar(15) DEFAULT NULL,
  `mikrotik_winbox_port` int(11) DEFAULT 8291,
  `mikrotik_web_port` int(11) DEFAULT 80,
  `public_winbox_port` int(11) DEFAULT NULL,
  `public_web_port` int(11) DEFAULT NULL,
  `is_active` tinyint(1) DEFAULT 0,
  `created_at` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `vpn_username` (`vpn_username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Inventory / Aset & Gudang
CREATE TABLE IF NOT EXISTS assets (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `category` varchar(64) DEFAULT 'modem',
  `brand` varchar(64) DEFAULT NULL,
  `mac_address` varchar(32) DEFAULT NULL,
  `serial_number` varchar(64) DEFAULT NULL,
  `purchase_price` decimal(15,2) DEFAULT 0,
  `purchase_date` date DEFAULT NULL,
  `status` varchar(32) DEFAULT 'available',
  `assigned_to_type` varchar(32) DEFAULT NULL,
  `assigned_to_id` int(11) DEFAULT NULL,
  `notes` text DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT current_timestamp(),
  `updated_at` timestamp NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_serial` (`serial_number`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS asset_logs (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `asset_id` int(11) NULL,
  `action` varchar(64) DEFAULT NULL,
  `entity_type` varchar(32) DEFAULT NULL,
  `entity_id` int(11) DEFAULT NULL,
  `admin_id` int(11) DEFAULT NULL,
  `action_date` timestamp NULL DEFAULT current_timestamp(),
  `notes` text DEFAULT NULL,
  PRIMARY KEY (`id`),
  FOREIGN KEY (`asset_id`) REFERENCES assets(`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- =============================================
-- ODC (Optical Distribution Cabinet)
-- =============================================
CREATE TABLE IF NOT EXISTS odcs (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `address` varchar(255) DEFAULT NULL,
  `coordinates` varchar(64) DEFAULT NULL,
  `capacity` int(11) DEFAULT 8,
  `olt_id` int(11) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- =============================================
-- OLT (Optical Line Terminal)
-- =============================================
CREATE TABLE IF NOT EXISTS olts (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `ip_address` varchar(64) DEFAULT NULL,
  `brand` varchar(64) DEFAULT NULL,
  `api_port` int(11) DEFAULT 8728,
  `username` varchar(64) DEFAULT NULL,
  `password` varchar(255) DEFAULT NULL,
  `total_ports` int(11) DEFAULT 0,
  `created_at` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- =============================================
-- Income Ledger (Keuangan / Laporan)
-- =============================================
CREATE TABLE IF NOT EXISTS income_ledger (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `source_type` varchar(32) DEFAULT NULL,
  `description` text DEFAULT NULL,
  `net_profit` decimal(15,2) DEFAULT 0,
  `gross_amount` decimal(15,2) DEFAULT 0,
  `cost_amount` decimal(15,2) DEFAULT 0,
  `created_at` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- =============================================
-- Expenses (Pengeluaran)
-- =============================================
CREATE TABLE IF NOT EXISTS expenses (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `category` varchar(64) DEFAULT NULL,
  `description` text DEFAULT NULL,
  `amount` decimal(15,2) DEFAULT 0,
  `expense_date` date DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- =============================================
-- FreeRADIUS radcheck (authentication)
-- =============================================
CREATE TABLE IF NOT EXISTS radcheck (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(64) NOT NULL,
  `attribute` varchar(64) NOT NULL DEFAULT 'Cleartext-Password',
  `op` char(2) NOT NULL DEFAULT ':=',
  `value` varchar(253) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `username` (`username`(32))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- =============================================
-- FreeRADIUS radusergroup
-- =============================================
CREATE TABLE IF NOT EXISTS radusergroup (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(64) NOT NULL,
  `groupname` varchar(64) NOT NULL,
  `priority` int(11) DEFAULT 1,
  PRIMARY KEY (`id`),
  KEY `username` (`username`(32))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
