from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from web.database import execute_query
import json

portal_settings_bp = Blueprint('portal_settings', __name__, template_folder='../../templates/portal_settings')

@portal_settings_bp.route('/', methods=['GET', 'POST'])
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    if request.method == 'POST':
        template_choice = request.form.get('portal_template', 'default')
        custom_html = request.form.get('portal_custom_html', '')
        custom_css = request.form.get('portal_custom_css', '')
        ticker_text = request.form.get('portal_ticker_text', '')
        trial_enabled = request.form.get('portal_trial_enabled', '0')
        logo_url = request.form.get('portal_logo_url', '')
        background_url = request.form.get('portal_background_url', '')
        domain_vpn = request.form.get('portal_domain_vpn', 'portal.mikrofun')
        
        # New Premium Fields
        cs_number = request.form.get('portal_cs_number', '')
        show_pricing = request.form.get('portal_show_pricing', '1')
        welcome_title = request.form.get('portal_welcome_title', '')
        welcome_subtitle = request.form.get('portal_welcome_subtitle', '')

        settings = {
            'portal_template': template_choice,
            'portal_custom_html': custom_html,
            'portal_custom_css': custom_css,
            'portal_ticker_text': ticker_text,
            'portal_trial_enabled': trial_enabled,
            'portal_logo_url': logo_url,
            'portal_background_url': background_url,
            'portal_domain_vpn': domain_vpn,
            'portal_cs_number': cs_number,
            'portal_show_pricing': show_pricing,
            'portal_welcome_title': welcome_title,
            'portal_welcome_subtitle': welcome_subtitle
        }

        for key, val in settings.items():
            execute_query(
                "INSERT INTO settings (setting_key, setting_value) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE setting_value=%s",
                (key, val, val)
            )
            
        flash('Pengaturan Portal berhasil disimpan.', 'success')
        return redirect(url_for('portal_settings.index'))
            
    # Load current settings
    keys = ['portal_template', 'portal_custom_html', 'portal_custom_css', 
            'portal_ticker_text', 'portal_trial_enabled', 'portal_logo_url', 'portal_background_url',
            'portal_cs_number', 'portal_show_pricing', 'portal_welcome_title', 'portal_welcome_subtitle']
    
    query = f"SELECT setting_key, setting_value FROM settings WHERE setting_key IN ({','.join(['%s']*len(keys))})"
    settings_rows = execute_query(query, tuple(keys), fetch=True) or []
    settings_dict = {row['setting_key']: row['setting_value'] for row in settings_rows}
    
    return render_template('portal_settings/index.html', settings=settings_dict)

@portal_settings_bp.route('/sync_walled_garden', methods=['POST'])
def sync_walled_garden():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
    try:
        from web.mikrotik_api import MikrotikApi
        routers = execute_query("SELECT id, name, vpn_ip, api_port, api_user, api_password FROM routers WHERE status='online'", fetch=True) or []
        
        domains_to_whitelist = [
            # Domain Portal Login (wajib agar portal bisa diakses sebelum login)
            'portal.mikrofun',
            # Tripay (jika dipakai sebagai gateway pembayaran)
            '*tripay.co.id',
            'tripay.co.id'
            # Midtrans TIDAK perlu di-whitelist karena semua API call
            # terjadi di server (server-to-server). QR di-render lokal.
        ]
        
        success_count = 0
        details = []
        
        for r in routers:
            api = MikrotikApi(r['vpn_ip'], r['api_port'])
            if api.login(r['api_user'], r['api_password']):
                success, msg = api.sync_walled_garden(domains_to_whitelist)
                api.close()
                details.append(f"{r['name']}: {msg}")
                if success: success_count += 1
            else:
                details.append(f"{r['name']}: Login Failed")
                
        return jsonify({
            'success': True,
            'message': f'Berhasil sinkronisasi ke {success_count} router.',
            'details': details
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
