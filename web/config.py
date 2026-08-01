import os
import sys

# Database Configuration
_db_password = os.environ.get('DB_PASSWORD')
if not _db_password:
    raise RuntimeError("DB_PASSWORD environment variable not set")

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'user': os.environ.get('DB_USER', 'radius'),
    'password': _db_password,
    'database': os.environ.get('DB_NAME', 'radius_db')
}

# RADIUS Configuration
_radius_secret = os.environ.get('RADIUS_SECRET')
if not _radius_secret:
    raise RuntimeError("RADIUS_SECRET environment variable not set")
RADIUS_SECRET = _radius_secret
AUTH_PORT = 1812
ACCT_PORT = 1813

# Path Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, 'logs')

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

RADIUS_LOG_PATH = os.path.join(LOG_DIR, 'radius.log')
DB_ERROR_LOG_PATH = os.path.join(LOG_DIR, 'db_error.log')

# App Version
APP_VERSION = "7.5.0"
