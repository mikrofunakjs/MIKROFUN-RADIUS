"""
MikroFun App Logger
Writes application logs to the database `app_logs` table.
"""
from web.database import execute_query
import traceback
import datetime

def write_log(level: str, message: str, detail: str = ''):
    """
    Write a log entry to the database.
    level: INFO | WARNING | ERROR
    """
    try:
        execute_query(
            "INSERT INTO app_logs (level, message, detail, created_at) VALUES (%s, %s, %s, NOW())",
            (level.upper(), str(message)[:500], str(detail)[:2000])
        )
    except Exception:
        # Silently fail so logging never crashes the app
        pass

def log_info(message: str, detail: str = ''):
    write_log('INFO', message, detail)

def log_warning(message: str, detail: str = ''):
    write_log('WARNING', message, detail)

def log_error(message: str, exc: Exception = None):
    """Log an error, optionally with an exception traceback."""
    detail = ''
    if exc:
        detail = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    write_log('ERROR', message, detail)
