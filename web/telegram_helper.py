"""
Telegram Bot Helper Module
Handles sending notifications to the ISP Owner/Admin via Telegram API.
"""
import requests
from web.database import execute_query

def get_telegram_settings():
    """Retrieve Telegram configuration from the database."""
    settings = execute_query("SELECT setting_key, setting_value FROM settings WHERE setting_key IN ('telegram_bot_token', 'telegram_chat_id')", fetch=True)
    if not settings:
        return None, None
        
    config = {s['setting_key']: s['setting_value'] for s in settings}
    return config.get('telegram_bot_token'), config.get('telegram_chat_id')

def send_telegram_message(message, parse_mode='Markdown'):
    """
    Send a message to the configured Telegram Chat ID.
    Returns (success_boolean, response_text_or_error)
    """
    token, chat_id = get_telegram_settings()
    
    if not token or not chat_id:
        return False, "Telegram Bot Token atau Chat ID belum dikonfigurasi."
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': parse_mode
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response_data = response.json()
        
        if response_data.get('ok'):
            return True, "Berhasil terkirim"
        else:
            return False, response_data.get('description', 'Unknown API Error')
    except Exception as e:
        return False, str(e)

def send_telegram_document(file_path, caption=""):
    """
    Send a document (like a database backup .sql or .zip file) to Telegram.
    Returns (success_boolean, response_text_or_error)
    """
    token, chat_id = get_telegram_settings()
    
    if not token or not chat_id:
        return False, "Telegram Bot Token atau Chat ID belum dikonfigurasi."
        
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    
    try:
        with open(file_path, 'rb') as document:
            payload = {
                'chat_id': chat_id,
                'caption': caption,
                'parse_mode': 'Markdown'
            }
            files = {
                'document': document
            }
            
            response = requests.post(url, data=payload, files=files, timeout=60)
            response_data = response.json()
            
            if response_data.get('ok'):
                return True, "Dokumen berhasil terkirim"
            else:
                return False, response_data.get('description', 'Unknown API Error')
    except Exception as e:
        return False, str(e)
