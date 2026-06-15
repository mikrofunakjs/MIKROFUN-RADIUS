from flask import Blueprint, render_template, request, session, redirect, url_for, send_file, flash, render_template_string, jsonify
from web.database import execute_query
import io
import zipfile
import time
from web.tripay_helper import TripayHelper
from web.midtrans_helper import MidtransHelper

portal_bp = Blueprint('portal', __name__, template_folder='../templates/portal')

@portal_bp.route('/login', methods=['GET', 'POST'])
def hotspot_login():
    """
    Handles ONLY IFrame/Redirect method (NAT API method removed as requested).
    """
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    mac = request.args.get('mac', '')
    ip = request.args.get('ip', client_ip)
    router_id = request.args.get('router_id')

    # If POST is somehow hit here, it means form wasn't configured properly in HTML
    # Because action should be the Mikrotik router's link_login URL
    if request.method == 'POST':
        pass

    # 3. Render GET
    link_login = request.args.get('link-login', '')
    link_orig = request.args.get('link-orig', '')
    error = request.args.get('error', '')
    url_username = request.args.get('username', '')

    # Load All Portal & App Settings
    keys = ['app_name', 'portal_template', 'portal_custom_html', 'portal_custom_css', 
            'portal_ticker_text', 'portal_trial_enabled', 'portal_logo_url', 'portal_background_url',
            'portal_cs_number', 'portal_show_pricing', 'portal_welcome_title', 'portal_welcome_subtitle',
            'active_gateway']
    query = f"SELECT setting_key, setting_value FROM settings WHERE setting_key IN ({','.join(['%s']*len(keys))})"
    settings_rows = execute_query(query, tuple(keys), fetch=True) or []
    settings = {row['setting_key']: row['setting_value'] for row in settings_rows}

    profiles = []
    if settings.get('portal_show_pricing', '1') == '1':
        profiles = execute_query("SELECT name, price, validity, validity_unit FROM profiles WHERE type IN ('hotspot', 'voucher') ORDER BY price ASC", fetch=True) or []

    hotspot_name = settings.get('app_name', 'MikroFun Hotspot')
    template_choice = settings.get('portal_template', 'default')

    if template_choice == 'custom' and settings.get('portal_custom_html'):
        return render_template_string(
            settings['portal_custom_html'],
            mac=mac,
            ip=ip,
            is_nat_mode=False,
            router_id=router_id,
            link_login=link_login,
            link_orig=link_orig,
            error=error,
            username=url_username,
            hotspot_name=hotspot_name,
            settings=settings,
            profiles=profiles
        )

    template_file = 'portal/login.html'
    if template_choice == 'isp_elegant':
        template_file = 'portal/isp_elegant.html'

    return render_template(
        template_file,
        mac=mac,
        ip=ip,
        is_nat_mode=False,
        router_id=router_id,
        link_login=link_login,
        link_orig=link_orig,
        error=error,
        username=url_username,
        hotspot_name=hotspot_name,
        settings=settings,
        profiles=profiles
    )

@portal_bp.route('/status')
def hotspot_status():
    """Success page after login"""
    # Load app name
    res = execute_query("SELECT setting_value FROM settings WHERE setting_key='app_name'", fetch_one=True)
    hotspot_name = res['setting_value'] if res else 'MikroFun'
    return render_template('portal/status.html', hotspot_name=hotspot_name)

@portal_bp.route('/admin')
def admin_portal():
    """
    Admin page explaining the Centralized Portal and allowing the download
    of the required Mikrotik redirect file.
    """
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    # Domain portal hardcoded untuk kemudahan pengguna
    settings = {'portal_domain_vpn': 'portal.mikrofun'}
    
    # Resolve host to IP for MikroTik NAT script (MikroTik refuses domain names in to-addresses)
    import re
    raw_host = request.host.split(':')[0]
    
    # PERHATIAN: Jika menggunakan domain (apalagi di balik Cloudflare), 
    # HP akan error 1001 "DNS Resolution Error" saat diredirect oleh router Mikrotik.
    # Oleh karena itu, jika host adalah domain, selalu default ke IP VPN.
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', raw_host):
        current_ip = raw_host
        current_port = request.host.split(':')[1] if ':' in request.host else '80'
    else:
        # Fallback to standard VPN IP if accessed via Domain
        current_ip = '10.66.66.1'
        current_port = '5000' # Gunakan port asli aplikasi di dalam VPN
    
    return render_template('portal/index.html', settings=settings, current_ip=current_ip, current_port=current_port)

@portal_bp.route('/download_redirect')
def download_redirect():
    """
    Generates a zip file containing a 'login.html' that redirects
    users to this server's /portal/login route.
    """
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    # Domain portal hardcoded
    custom_domain = 'portal.mikrofun'

    # Choose redirect mode: public (internet) or vpn (local tunnel)
    mode = request.args.get('mode', 'public')
    
    if mode == 'vpn':
        # Local DNS over VPN (uses the custom domain from settings)
        portal_url = f"http://{custom_domain}/portal/login"
    else:
        # Smart Protocol Detection (Handling HTTPS behind proxy for Public access)
        protocol = "https" if request.is_secure or request.headers.get('X-Forwarded-Proto') == 'https' else "http"
        # User said their web is already https, so let's ensure it's used
        if "https" in request.host_url: protocol = "https"
        
        server_url = f"{protocol}://{request.host.rstrip('/')}"
        portal_url = f"{server_url}/portal/login"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Hotspot Login</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        body, html {{ margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #0f172a; }}
        iframe {{ width: 100%; height: 100%; border: none; }}
        #loader {{ position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: #0f172a; display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 9999; color: white; font-family: sans-serif; transition: opacity 0.5s; }}
        .spinner {{ border: 3px solid rgba(255,255,255,0.1); border-top: 3px solid #0ea5e9; border-radius: 50%; width: 30px; height: 30px; animation: spin 1s linear infinite; margin-bottom: 15px; }}
        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
    </style>
</head>
<body>
    <div id="loader">
        <div class="spinner"></div>
        <div style="font-size: 13px; opacity: 0.7;">Memuat Portal...</div>
    </div>
    <script>
        const portalUrl = "{portal_url}";
        const queryParams = "?mac=$(mac)&ip=$(ip)&username=$(username)&link-login=$(link-login-only)&link-orig-esc=$(link-orig-esc)&error=$(error)";
        // Tambahkan iframe secara dinamis agar parameter ter-parse dulu oleh Mikrotik
        document.write('<iframe id="portalFrame" src="' + portalUrl + queryParams + '" allow="geolocation" allowtransparency="true" style="width:100%;height:100%;border:none;"></iframe>');
        
        // Hide loader when iframe is ready
        document.getElementById('portalFrame').onload = function() {{
            document.getElementById('loader').style.opacity = '0';
            setTimeout(function() {{ document.getElementById('loader').style.display = 'none'; }}, 500);
        }};
    </script>
</body>
</html>"""

    # Fallback Status Page for Mikrotik (Auto Redirects to VPS Status)
    html_status_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Koneksi Berhasil</title>
    <meta http-equiv="refresh" content="0; url={portal_url.replace('/login', '/status')}">
    <script>window.location.replace("{portal_url.replace('/login', '/status')}");</script>
</head>
<body style="background:#0f172a;color:white;text-align:center;padding-top:100px;font-family:sans-serif;">
    <p>Otentikasi Berhasil. Mengalihkan ke halaman status...</p>
</body>
</html>"""

    # Create an in-memory ZIP
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Include login, index, and status for maximum compatibility
        zf.writestr('login.html', html_content)
        zf.writestr('index.html', html_content)
        zf.writestr('status.html', html_status_content)
    
    memory_file.seek(0)
    
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name='mikrofun_hotspot_v2.zip'
    )

@portal_bp.route('/api/checkout', methods=['POST'])
def api_checkout():
    """
    Called by Captive Portal via AJAX to generate an invoice.
    Because the user is unauthenticated, we rely entirely on the POST payload.
    """
    data = request.json
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    phone = data.get('phone')
    method = data.get('method')  # e.g., 'QRIS', 'BCAVA'
    profile_name = data.get('profile_name')
    mac = data.get('mac')
    ip = data.get('ip')
    router_id = data.get('router_id')

    # Find the corresponding profile
    profile = execute_query("SELECT id, name, price FROM profiles WHERE name=%s LIMIT 1", (profile_name,), fetch_one=True)
    if not profile:
        return jsonify({'success': False, 'message': 'Paket tidak ditemukan'}), 404

    amount = int(profile['price'])
    
    # Check gateway settings
    settings_rows = execute_query("SELECT setting_key, setting_value FROM settings WHERE setting_key IN ('active_gateway')", fetch=True) or []
    settings = {row['setting_key']: row['setting_value'] for row in settings_rows}
    active_gateway = settings.get('active_gateway', 'tripay').lower()
    
    customer_data = {
        'first_name': phone,
        'email': f"{phone}@captive.local",
        'phone': phone
    }
    order_items = [{
        'name': f"Voucher Hotspot {profile['name']}",
        'price': amount,
        'quantity': 1
    }]

    merchant_ref = f"CP-{mac.replace(':','')}-{int(time.time())}" if mac else f"CP-VCH-{int(time.time())}"

    # Insert Pending Transaction into Payments Table
    execute_query("""
        INSERT INTO payments (amount, payment_type, status, sender_bank, guest_phone, profile_id, payment_date)
        VALUES (%s, 'voucher', 'pending', %s, %s, %s, NOW())
    """, (amount, method, phone, profile['id']))
    
    payment_id = execute_query("SELECT LAST_INSERT_ID() as id", fetch_one=True)['id']
    merchant_ref = f"INV-{payment_id}-{int(time.time())}"

    gateway_error = None
    response_data = {'success': True, 'merchant_ref': merchant_ref, 'amount': amount}

    if active_gateway == 'midtrans':
        helper = MidtransHelper()
        midtrans_data, error = helper.create_qris_charge(merchant_ref, amount, customer_data)
        if error or not midtrans_data:
            gateway_error = error or "Failed to create QRIS"
        else:
            execute_query("UPDATE payments SET external_ref=%s WHERE id=%s", (merchant_ref, payment_id))
            response_data.update({
                'transaction_id': merchant_ref,
                'qr_string': midtrans_data.get('qr_string'),
                'gateway': 'midtrans'
            })
    else:
        # Default Tripay
        helper = TripayHelper()
        tripay_data, error = helper.request_transaction(
            method=method,
            amount=amount,
            customer_data=customer_data,
            order_items=order_items,
            merchant_ref=merchant_ref
        )
        if error or not tripay_data:
            gateway_error = error or "Gateway Error"
        else:
            execute_query("UPDATE payments SET external_ref=%s WHERE id=%s", (tripay_data.get('reference'), payment_id))
            response_data.update({
                'transaction_id': tripay_data.get('reference'),
                'qr_url': tripay_data.get('qr_url'),
                'pay_code': tripay_data.get('pay_code'),
                'checkout_url': tripay_data.get('checkout_url')
            })

    if gateway_error:
        execute_query("UPDATE payments SET status='failed' WHERE id=%s", (payment_id,))
        return jsonify({'success': False, 'message': f'Gateway Error: {gateway_error}'}), 500

    return jsonify(response_data)

@portal_bp.route('/api/check_payment', methods=['GET'])
def check_payment():
    """
    Polling endpoint for captive portal to check if invoice is paid.
    """
    ref = request.args.get('invoice_id')
    if not ref:
        return jsonify({'paid': False}), 400
        
    # Check if transaction is PAID and optionally if voucher was generated
    payment = execute_query("SELECT status, voucher_code FROM payments WHERE external_ref=%s OR id=%s LIMIT 1", (ref, ref), fetch_one=True)
    
    if payment and payment['status'] in ('paid', 'settlement', 'approved'):
        return jsonify({
            'paid': True,
            'voucher_code': payment.get('voucher_code')
        })
        
    return jsonify({'paid': False})
