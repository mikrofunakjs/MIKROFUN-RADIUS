from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from decorators import admin_required
from web.database import execute_query

telegram_bot_bp = Blueprint('telegram_bot', __name__, template_folder='../../templates/telegram_bot')

def get_telegram_settings():
    rows = execute_query("SELECT setting_key, setting_value FROM settings WHERE setting_key IN ('telegram_bot_token', 'telegram_chat_id')", fetch=True)
    settings = {
        'telegram_bot_token': '',
        'telegram_chat_id': ''
    }
    if rows:
        for r in rows:
            settings[r['setting_key']] = r['setting_value']
    return settings

def set_setting(key, value):
    val = value if value is not None else ''
    execute_query("""
        INSERT INTO settings (setting_key, setting_value) 
        VALUES (%s, %s) 
        ON DUPLICATE KEY UPDATE setting_value=%s
    """, (key, val, val))

@telegram_bot_bp.route('/', methods=['GET', 'POST'])
@admin_required
def index():
    if session.get('role') == 'cs':
        flash('Akses ditolak. Fitur ini hanya untuk Admin.', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        bot_token = request.form.get('telegram_bot_token')
        chat_id = request.form.get('telegram_chat_id')

        set_setting('telegram_bot_token', bot_token)
        set_setting('telegram_chat_id', chat_id)
        
        flash('Konfigurasi Telegram Bot berhasil disimpan.', 'success')
        return redirect(url_for('telegram_bot.index'))

    settings = get_telegram_settings()
    return render_template('telegram_bot/index.html', settings=settings)

@telegram_bot_bp.route('/test_send', methods=['POST'])
@admin_required
def test_send():
    if session.get('role') == 'cs':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    from web.telegram_helper import send_telegram_message
    
    test_msg = "🤖 *MikroFun Test Message*\n\nJika Anda membaca pesan ini, integrasi Telegram Bot ke sistem MikroFun telah berhasil!"
    success, msg = send_telegram_message(test_msg)
    
    return jsonify({
        'success': success,
        'message': msg
    })
