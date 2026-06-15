from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from decorators import admin_required
from web.database import execute_query
from web.wa_helper import WA_API_KEY
import requests
import socket
import ipaddress

wa_gateway_bp = Blueprint('wa_gateway', __name__, template_folder='../../templates/wa_gateway')

ALLOWED_PROVIDERS = ('fonnte', 'baileys')

def _resolve_endpoint_url(endpoint, path):
    """Resolve endpoint hostname to IP and return safe URL (prevents DNS rebinding)."""
    from urllib.parse import urlparse
    parsed = urlparse(endpoint)
    host = parsed.hostname or '127.0.0.1'
    ip = socket.gethostbyname(host) if host not in ('localhost', '127.0.0.1', '::1') else host
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{ip}{port}{path}"

def _is_safe_endpoint(url):
    """Validate that endpoint URL resolves to a safe host (localhost or private IP ranges)."""
    if not url:
        return False
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        host = parsed.hostname
        if not host:
            return False
        if host in ('localhost', '127.0.0.1', '::1'):
            return True
        socket.setdefaulttimeout(3)
        resolved_ip = socket.gethostbyname(host)
        addr = ipaddress.ip_address(resolved_ip)
        if addr.is_loopback or addr.is_private:
            return True
        return False
    except Exception:
        return False

def get_settings():
    """Helper to fetch WA settings into a dictionary"""
    rows = execute_query("SELECT setting_key, setting_value FROM settings WHERE setting_key IN ('wa_provider', 'fonnte_token', 'wa_baileys_endpoint')", fetch=True)
    settings = {
        'wa_provider': 'fonnte',
        'fonnte_token': '',
        'wa_baileys_endpoint': 'http://127.0.0.1:3000'
    }
    if rows:
        for r in rows:
            settings[r['setting_key']] = r['setting_value']
    return settings

def set_setting(key, value):
    """Update or insert a setting"""
    val = value if value is not None else ''
    execute_query("""
        INSERT INTO settings (setting_key, setting_value) 
        VALUES (%s, %s) 
        ON DUPLICATE KEY UPDATE setting_value=%s
    """, (key, val, val))

def get_reminder_settings():
    """Fetch reminder-specific settings"""
    rows = execute_query(
        "SELECT setting_key, setting_value FROM settings WHERE setting_key IN ('wa_reminder_enabled', 'wa_reminder_days')",
        fetch=True
    )
    settings = {'wa_reminder_enabled': '1', 'wa_reminder_days': '3'}
    if rows:
        for r in rows:
            settings[r['setting_key']] = r['setting_value']
    return settings

@wa_gateway_bp.route('/', methods=['GET', 'POST'])
@admin_required
def index():
    if request.method == 'POST':
        wa_provider = request.form.get('wa_provider', '').strip().lower()
        fonnte_token = request.form.get('fonnte_token', '').strip()
        baileys_endpoint = request.form.get('wa_baileys_endpoint', '').strip()

        if not wa_provider or wa_provider not in ALLOWED_PROVIDERS:
            flash('Provider WhatsApp harus dipilih (fonnte atau baileys).', 'error')
            return redirect(url_for('wa_gateway.index'))

        if wa_provider == 'baileys' and baileys_endpoint and not _is_safe_endpoint(baileys_endpoint):
            flash('Endpoint Baileys harus berupa alamat localhost atau IP private.', 'error')
            return redirect(url_for('wa_gateway.index'))

        set_setting('wa_provider', wa_provider)
        set_setting('fonnte_token', fonnte_token)
        set_setting('wa_baileys_endpoint', baileys_endpoint)

        flash('Konfigurasi WhatsApp Gateway berhasil disimpan.', 'success')
        return redirect(url_for('wa_gateway.index'))

    settings = get_settings()
    reminder = get_reminder_settings()
    return render_template('wa_gateway/index.html', settings=settings, reminder=reminder)

@wa_gateway_bp.route('/reminder/save', methods=['POST'])
@admin_required
def save_reminder():
    enabled = request.form.get('wa_reminder_enabled', '0')
    days = request.form.get('wa_reminder_days', '3').strip()

    if not days.isdigit() or int(days) < 1 or int(days) > 30:
        flash('Jumlah hari harus antara 1-30.', 'error')
        return redirect(url_for('wa_gateway.index') + '#reminder')

    set_setting('wa_reminder_enabled', enabled)
    set_setting('wa_reminder_days', days)

    flash('Pengaturan pengingat tagihan berhasil disimpan.', 'success')
    return redirect(url_for('wa_gateway.index') + '#reminder')

@wa_gateway_bp.route('/templates', methods=['GET'])
@admin_required
def templates():
    templates = execute_query("SELECT * FROM wa_templates", fetch=True) or []
    return render_template('wa_gateway/templates.html', templates=templates)

@wa_gateway_bp.route('/templates/update', methods=['POST'])
@admin_required
def update_template():
    template_id = request.form.get('id')
    message_text = request.form.get('message_text')

    if not template_id or not message_text:
        flash('ID dan Pesan wajib diisi.', 'error')
        return redirect(url_for('wa_gateway.templates'))

    verify = execute_query("SELECT id FROM wa_templates WHERE id=%s", (template_id,), fetch_one=True)
    if not verify:
        flash('Template tidak ditemukan.', 'error')
        return redirect(url_for('wa_gateway.templates'))

    execute_query("UPDATE wa_templates SET message_text=%s WHERE id=%s", (message_text, template_id))
    flash('Template WA berhasil diperbarui.', 'success')
    return redirect(url_for('wa_gateway.templates'))

@wa_gateway_bp.route('/status', methods=['GET'])
@admin_required
def get_wa_status():
    """AJAX endpoint to check Node.js Baileys status"""
    settings = get_settings()
    endpoint = settings.get('wa_baileys_endpoint', 'http://127.0.0.1:3000')

    if not _is_safe_endpoint(endpoint):
        return jsonify({'status': 'offline', 'error': 'Endpoint tidak aman.'})

    try:
        safe_url = _resolve_endpoint_url(endpoint, '/status')
        resp = requests.get(safe_url, timeout=5, headers={'X-API-Key': WA_API_KEY})
        return jsonify(resp.json())
    except requests.exceptions.ConnectionError:
        return jsonify({'status': 'offline', 'error': 'Tidak dapat terhubung ke service Node.js.'})
    except requests.exceptions.Timeout:
        return jsonify({'status': 'offline', 'error': 'Timeout menghubungi service Node.js.'})
    except ValueError:
        return jsonify({'status': 'offline', 'error': 'Respon tidak valid dari service Node.js.'})
    except Exception as e:
        return jsonify({'status': 'offline', 'error': f'Kesalahan: {str(e)}'})

@wa_gateway_bp.route('/logout', methods=['POST'])
@admin_required
def logout_wa():
    """AJAX endpoint to command Node.js to logout Baileys session"""
    settings = get_settings()
    endpoint = settings.get('wa_baileys_endpoint', 'http://127.0.0.1:3000')

    if not _is_safe_endpoint(endpoint):
        return jsonify({'success': False, 'error': 'Endpoint tidak aman.'})

    try:
        safe_url = _resolve_endpoint_url(endpoint, '/logout')
        resp = requests.post(safe_url, timeout=5, headers={'X-API-Key': WA_API_KEY})
        return jsonify(resp.json())
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'error': 'Tidak dapat terhubung ke service Node.js.'})
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': 'Timeout menghubungi service Node.js.'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Terjadi kesalahan: {str(e)}'})

@wa_gateway_bp.route('/test_send', methods=['POST'])
@admin_required
def test_send():
    """Endpoint for dispatching a test WA message"""
    data = request.json
    target = data.get('target')
    message = data.get('message')

    if not target or not message:
        return jsonify({'success': False, 'error': 'Target dan pesan harus diisi.'})

    from web.wa_helper import send_wa

    try:
        success = send_wa(target, message)
        if success:
            return jsonify({'success': True, 'message': 'Pesan berhasil terkirim.'})
        else:
            return jsonify({'success': False, 'error': 'Gagal mengirim pesan. Periksa konfigurasi provider WA.'})
    except Exception:
        return jsonify({'success': False, 'error': 'Terjadi kesalahan internal saat mengirim pesan.'})
