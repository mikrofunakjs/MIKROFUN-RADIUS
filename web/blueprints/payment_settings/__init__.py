from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from web.database import execute_query

payment_settings_bp = Blueprint('payment_settings', __name__)

from web.decorators import admin_required

@payment_settings_bp.route('/', methods=['GET', 'POST'])
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    if request.method == 'POST':
        # Tripay Settings
        tripay_keys = ['tripay_api_key', 'tripay_private_key', 'tripay_merchant_code', 'tripay_mode']
        for key in tripay_keys:
            val = request.form.get(key)
            if val is not None:
                execute_query(
                    "INSERT INTO settings (setting_key, setting_value) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE setting_value=%s",
                    (key, val, val)
                )

        # Midtrans Settings
        midtrans_keys = ['midtrans_server_key', 'midtrans_client_key', 'midtrans_merchant_id', 'midtrans_mode']
        for key in midtrans_keys:
            val = request.form.get(key)
            if val is not None:
                execute_query(
                    "INSERT INTO settings (setting_key, setting_value) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE setting_value=%s",
                    (key, val, val)
                )

        # Moota Settings
        moota_keys = ['moota_api_key', 'moota_webhook_secret']
        for key in moota_keys:
            val = request.form.get(key)
            if val is not None:
                execute_query(
                    "INSERT INTO settings (setting_key, setting_value) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE setting_value=%s",
                    (key, val, val)
                )

        # Duitku Settings
        duitku_keys = ['duitku_merchant_code', 'duitku_api_key', 'duitku_mode']
        for key in duitku_keys:
            val = request.form.get(key)
            if val is not None:
                execute_query(
                    "INSERT INTO settings (setting_key, setting_value) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE setting_value=%s",
                    (key, val, val)
                )
                
        # Xendit Settings
        xendit_keys = ['xendit_api_key', 'xendit_webhook_token', 'xendit_mode']
        for key in xendit_keys:
            val = request.form.get(key)
            if val is not None:
                execute_query(
                    "INSERT INTO settings (setting_key, setting_value) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE setting_value=%s",
                    (key, val, val)
                )
                
        # Active Gateway
        active_gateway = request.form.get('active_gateway', 'manual')
        execute_query(
            "INSERT INTO settings (setting_key, setting_value) VALUES ('active_gateway', %s) "
            "ON DUPLICATE KEY UPDATE setting_value=%s",
            (active_gateway, active_gateway)
        )
        
        flash('Konfigurasi Payment Gateway disimpan.', 'success')
        return redirect(url_for('payment_settings.index'))
        
    # Load settings
    settings_rows = execute_query("SELECT * FROM settings", fetch=True) or []
    settings_dict = {row['setting_key']: row['setting_value'] for row in settings_rows}
    
    return render_template('payment_settings/index.html', settings=settings_dict)
