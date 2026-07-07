import os
import sys

# Database Configuration
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'user': os.environ.get('DB_USER', 'radius'),
    'password': os.environ.get('DB_PASSWORD', 'radiuspass123'),
    'database': os.environ.get('DB_NAME', 'radius_db')
}

# RADIUS Configuration
RADIUS_SECRET = os.environ.get('RADIUS_SECRET', 'testing123')
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
