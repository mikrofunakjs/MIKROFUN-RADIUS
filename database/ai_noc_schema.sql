-- radacct_snapshots: time-series traffic per user via RADIUS interim updates
CREATE TABLE IF NOT EXISTS radacct_snapshots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    acctsessionid VARCHAR(64) NOT NULL,
    username VARCHAR(64) NOT NULL,
    snapshot_time DATETIME NOT NULL DEFAULT NOW(),
    acctinputoctets BIGINT DEFAULT 0,
    acctoutputoctets BIGINT DEFAULT 0,
    acctsessiontime INT UNSIGNED DEFAULT 0,
    framedipaddress VARCHAR(15),
    callingstationid VARCHAR(50),
    nasipaddress VARCHAR(15),
    INDEX idx_username_time (username, snapshot_time),
    INDEX idx_session (acctsessionid, snapshot_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
