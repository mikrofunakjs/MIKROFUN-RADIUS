import os
from datetime import datetime
import json
import base64
import hashlib
import uuid
import platform
import requests
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LICENSE_FILE = os.path.join(BASE_DIR, '.license')

# Configuration
LICENSE_SERVER_URL = "https://mikrofun.site"

# HARDCODED PUBLIC KEY (Do NOT modify)
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxWf49Y561q8vmEu3EcUw
KCR+VElXrA66Rpzv9Kj2/iAJP0J46UTcplkQA96+PK8kGKZ2olDD6ZK7lYiVYh72
e2PFiqbqdMh9omFhGZUGQ3yifz4UhHzG4tCghB5oNmI8CU2p3E0g1oLpMLInvCKN
cYioAS4GMGruKhYDNDBI4Hu/6beUP5Hm2USx3V9n49nEvg84JSPLL8soGGPM9HgE
kw0jwqHsgrhRMmKRRzxkYE6kHdEb5LxGv9b0O0ze8cbIse2kS6clOqH3pZMmfNAH
9EHQMRDT+hMUf3vQBLeO/13yty7aKMygFNW8rolPGLYo1srBd0pJOzaopfhERU2/
6wIDAQAB
-----END PUBLIC KEY-----"""


def get_hwid():
    try:
        if os.path.exists('/etc/machine-id'):
            with open('/etc/machine-id', 'r') as f:
                return hashlib.sha256(f.read().strip().encode()).hexdigest()
        mac = uuid.getnode()
        system_info = f"{platform.system()}-{platform.machine()}-{mac}"
        return hashlib.sha256(system_info.encode()).hexdigest()
    except Exception:
        return "unknown-hwid"


def get_license_from_db():
    if not os.path.exists(LICENSE_FILE):
        return None
    with open(LICENSE_FILE, 'r') as f:
        return f.read().strip()


def save_license_to_db(license_key):
    with open(LICENSE_FILE, 'w') as f:
        f.write(license_key)


def remove_license_from_db():
    if os.path.exists(LICENSE_FILE):
        os.remove(LICENSE_FILE)


def verify_license_offline(license_key):
    try:
        if not license_key or '.' not in license_key:
            return False, "Format Lisensi Salah"

        from Crypto.PublicKey import RSA
        from Crypto.Signature import pkcs1_15
        from Crypto.Hash import SHA256

        public_key = RSA.import_key(PUBLIC_KEY_PEM.encode())

        payload_b64, sig_b64 = license_key.split('.')
        payload_bytes = base64.b64decode(payload_b64)
        signature = base64.b64decode(sig_b64)

        h = SHA256.new(payload_bytes)
        try:
            pkcs1_15.new(public_key).verify(h, signature)
        except (ValueError, TypeError):
            return False, "Tanda Tangan Digital TIDAK Valid!"

        data = json.loads(payload_bytes.decode('utf-8'))

        exp_str = data.get('exp') or data.get('expiry_date')
        if not exp_str:
            return False, "Format Lisensi Salah (No Expiry Date)"

        try:
            exp_date = datetime.strptime(exp_str, '%Y-%m-%d')
            if datetime.now() > exp_date:
                return False, f"Lisensi Kadaluarsa pada {exp_str}"
        except ValueError:
            return False, "Format Tanggal Expired Salah"

        license_hwid = data.get('hwid')
        if license_hwid:
            current_hwid = get_hwid()
            if license_hwid != current_hwid:
                return False, "Lisensi ini tidak terdaftar untuk perangkat ini (HWID Mismatch)"

        return True, f"Lisensi Valid S/D {exp_str}"

    except Exception as e:
        return False, f"Error Verifikasi: {str(e)}"


_premium_cache = {
    'status': None,
    'last_checked': 0
}


def is_premium():
    global _premium_cache

    now = time.time()
    if _premium_cache['status'] is not None and (now - _premium_cache['last_checked'] < 300):
        return _premium_cache['status']

    key = get_license_from_db()
    if not key:
        _premium_cache['status'] = False
        _premium_cache['last_checked'] = now
        return False

    valid, _ = verify_license_offline(key)
    if not valid:
        remove_license_from_db()
        _premium_cache['status'] = False
        _premium_cache['last_checked'] = now
        return False

    _premium_cache['status'] = True
    _premium_cache['last_checked'] = now
    return True


def get_isp_name():
    if is_premium():
        try:
            from database import execute_query
            row = execute_query(
                "SELECT setting_value FROM settings WHERE setting_key='company_name'",
                fetch_one=True
            )
            if row and row.get('setting_value'):
                return row['setting_value']
        except Exception:
            pass
    return 'MikroFun'


def activate_license_online(license_key):
    try:
        import socket
        machine_name = socket.gethostname()

        url = f"{LICENSE_SERVER_URL}/api/validate-license"
        payload = {
            'license_key': license_key,
            'machine_name': machine_name,
            'hwid': get_hwid()
        }

        response = requests.post(url, json=payload, timeout=10)

        if 'application/json' not in response.headers.get('Content-Type', ''):
            return False, f"Server tidak memberikan respon JSON. Status: {response.status_code}. Pastikan URL benar."

        try:
            data = response.json()
        except Exception:
            return False, f"Gagal membaca respon server (Bukan JSON valid). Status: {response.status_code}"

        if data.get('valid'):
            full_license = data.get('license_data') or data.get('signed_license') or license_key
            save_license_to_db(full_license)

            global _premium_cache
            _premium_cache['status'] = True
            _premium_cache['last_checked'] = time.time()

            return True, data.get('message')
        else:
            return False, data.get('message')

    except Exception as e:
        return False, f"Gagal koneksi ke server lisensi: {e}"
