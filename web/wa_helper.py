import requests
import re
import time
import os
import traceback
from web.database import execute_query

WA_API_KEY = os.environ.get('WA_API_KEY', 'mikrofun-wa-secret-key')

def get_setting(key, default=None):
    """Fetch setting value from DB"""
    try:
        row = execute_query("SELECT setting_value FROM settings WHERE setting_key=%s", (key,), fetch_one=True)
        return row['setting_value'] if row and row['setting_value'] else default
    except Exception as e:
        print(f"Error fetching setting {key}: {e}")
        return default

def _validate_phone(target):
    """Validate target phone number has minimum digits."""
    if not target:
        return False
    clean = str(target).replace('@s.whatsapp.net', '').replace('+', '').replace(' ', '').replace('-', '')
    clean = re.sub(r'\D', '', clean)
    return len(clean) >= 8

def send_wa(target, message):
    """
    Send WhatsApp message using configured provider.
    target: Phone number (e.g., 08123456789)
    message: Text message
    """
    if not _validate_phone(target):
        print(f"WA Error: Invalid target number: {target}")
        return False

    provider = get_setting('wa_provider', 'fonnte')

    if provider == 'baileys':
        return send_baileys(target, message)
    elif provider == 'fonnte':
        return send_fonnte(target, message)
    else:
        print(f"WA Warning: Unknown provider '{provider}', defaulting to fonnte.")
        return send_fonnte(target, message)

def send_fonnte(target, message):
    token = get_setting('fonnte_token')
    if not token:
        print("WA Error: Fonnte Token not set.")
        return False

    url = "https://api.fonnte.com/send"
    headers = {"Authorization": token}
    data = {"target": target, "message": message}

    try:
        response = requests.post(url, headers=headers, data=data, timeout=10)
        print(f"WA Fonnte Response [{response.status_code}]: {response.text[:200]}")
        if response.status_code != 200:
            print(f"WA Fonnte Error: HTTP {response.status_code}")
            return False
        res_json = response.json()
        status_val = res_json.get('status')
        if status_val in (True, 'true', 'True', 1, '1', 'success'):
            return True
        else:
            print(f"WA Fonnte Error: {res_json.get('reason', 'Unknown error')}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"WA Fonnte Error: Connection failed.")
        return False
    except requests.exceptions.Timeout:
        print(f"WA Fonnte Error: Request timeout.")
        return False
    except Exception as e:
        print(f"WA Fonnte Error: {e}")
        return False

def _send_baileys_once(target, message):
    """Single attempt to send via Baileys. Returns (success_bool, retryable_bool)."""
    endpoint = get_setting('wa_baileys_endpoint', 'http://127.0.0.1:3000')
    if not endpoint:
        print("WA Error: Baileys endpoint not set.")
        return False, False

    url = f"{endpoint.rstrip('/')}/send"
    data = {"target": target, "message": message}
    headers = {"Content-Type": "application/json", "X-API-Key": WA_API_KEY}

    try:
        response = requests.post(url, json=data, headers=headers, timeout=10)
        if response.status_code == 429:
            print(f"WA Baileys: Rate limited by service.")
            return False, True
        res_json = response.json()
        print(f"WA Baileys Response: {res_json}")
        if response.status_code == 200 and res_json.get('success'):
            return True, False
        else:
            err = res_json.get('error', '')
            is_retryable = (response.status_code == 429 or
                            err == 'WhatsApp is not connected.')
            print(f"WA Baileys Error: {err}")
            return False, is_retryable
    except requests.exceptions.ConnectionError:
        print(f"WA Baileys Error: Connection refused to {url}.")
        return False, True
    except requests.exceptions.Timeout:
        print(f"WA Baileys Error: Request timeout to {url}.")
        return False, True
    except Exception as e:
        print(f"WA Baileys Exception: {e}")
        traceback.print_exc()
        return False, False

def send_baileys(target, message):
    """Send via Baileys with retry on transient failures."""
    for attempt in range(3):
        success, retryable = _send_baileys_once(target, message)
        if success:
            return True
        if not retryable:
            return False
        if attempt < 2:
            delay = 1.5 * (2 ** attempt)
            print(f"WA Baileys: Retrying in {delay:.1f}s (attempt {attempt + 2}/3)...")
            time.sleep(delay)
    return False

def _escape_template_value(val):
    """Escape curly braces in template replacement values, handle None gracefully."""
    if val is None:
        return ''
    s = str(val)
    s = s.replace('{', '{{').replace('}', '}}')
    return s

def send_wa_notification(target, template_key, **context):
    """
    Fetch template from DB and send rendered message via WA.
    template_key: key in wa_templates table
    context: variables to replace in template (e.g. code, name)
    """
    try:
        row = execute_query("SELECT message_text FROM wa_templates WHERE template_key=%s", (template_key,), fetch_one=True)
        if not row:
            print(f"WA Warning: Template '{template_key}' not found in DB.")
            fallback = context.get('fallback_message', '')
            if not fallback:
                return False
            return send_wa(target, fallback)

        message = row['message_text']
        for key in sorted(context.keys(), key=len, reverse=True):
            placeholder = "{" + key + "}"
            message = message.replace(placeholder, _escape_template_value(context[key]))

        remaining = re.findall(r'\{(\w+)\}', message)
        if remaining:
            print(f"WA Warning: Unresolved placeholders in template '{template_key}': {remaining}")
            message = re.sub(r'\{\w+\}', '', message)

        if not target or not message:
            return False

        return send_wa(target, message)
    except Exception as e:
        print(f"WA Notification Error: {e}")
        return False
