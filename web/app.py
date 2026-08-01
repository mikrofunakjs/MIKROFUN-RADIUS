"""
MikroFun Web Panel
"""
from flask import Flask, render_template, session, redirect, url_for, render_template_string, request
from jinja2.sandbox import SandboxedEnvironment
from jinja2 import TemplateNotFound
import os
import sys

# Add parent directory to path so 'web' package is resolvable
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
# Also add current dir just in case
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Python Path check removed for production security

if getattr(sys, 'frozen', False):
    # Running in PyInstaller Bundle
    base_dir = sys._MEIPASS
    template_folder = os.path.join(base_dir, 'web', 'templates')
    static_folder = os.path.join(base_dir, 'web', 'static')
    print(f"Frozen Mode: Using templates from {template_folder}")
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
    
    # Persistent Upload Folder (Next to Binary)
    # sys.executable points to the binary file. We want the dir containing it.
    base_exec_dir = os.path.dirname(sys.executable)
    UPLOAD_FOLDER = os.path.join(base_exec_dir, 'data', 'uploads')
else:
    # Running in Dev Mode
    app = Flask(__name__)
    UPLOAD_FOLDER = os.path.join(current_dir, 'static', 'uploads')

# Ensure Upload Folder Exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
print(f"Upload Folder: {UPLOAD_FOLDER}")

# --- SECURITY INTEGRITY CHECK ---
from web.integrity_check import verify_integrity
if not verify_integrity():
    print("FATAL: System Integrity Compromised! Application shutting down.")
    sys.exit(1)
# --- END SECURITY CHECK ---

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    from flask import send_from_directory, abort
    # This folder holds customer payment proofs; only staff may read it.
    if not session.get('logged_in'):
        abort(403)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# --- DYNAMIC SECRET KEY (DATABASE BACKED) ---
def get_secure_secret_key():
    from web.database import execute_query
    import secrets
    import string
    
    try:
        # Check if secret key exists in database
        res = execute_query("SELECT setting_value FROM settings WHERE setting_key='app_secret_key'", fetch_one=True)
        if res and res['setting_value']:
            return res['setting_value']
        
        # Generate new random key if not exists
        alphabet = string.ascii_letters + string.digits + string.punctuation
        new_key = ''.join(secrets.choice(alphabet) for _ in range(64))
        
        # Save to DB
        execute_query(
            "INSERT INTO settings (setting_key, setting_value) VALUES ('app_secret_key', %s) "
            "ON DUPLICATE KEY UPDATE setting_value=%s",
            (new_key, new_key)
        )
        return new_key
    except Exception as e:
        print(f"Warning: Could not fetch secret key from DB ({e}). Using temporary session key.")
        return secrets.token_hex(32)

app.secret_key = get_secure_secret_key()
app.config['SESSION_COOKIE_HTTPONLY'] = True
import os
# Only set SECURE cookie if deployed on HTTPS, otherwise it breaks HTTP logins
is_https = os.environ.get('USE_HTTPS', 'False').lower() in ('true', '1', 't')
app.config['SESSION_COOKIE_SECURE'] = is_https
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# --- SSTI SAFE RENDERING HELPER ---
def safe_render_template_string(source, **context):
    """Render a template string securely, avoiding Jinja2 SSTI vulnerabilities by using string replacement."""
    try:
        result = source
        company = context.get('company', {})
        
        # Replace company variables
        for k, v in company.items():
            result = result.replace(f'{{{{company.{k}}}}}', str(v))
            
        # Support common explicit placeholders
        result = result.replace('{{company_name}}', str(company.get('name', '')))
        result = result.replace('{{ company.name }}', str(company.get('name', '')))
        
        # Inject packages as a JSON string so frontend JS can render it if needed
        import json
        packages = context.get('packages', [])
        result = result.replace('{{packages_json}}', json.dumps(packages))
        
        return result
    except Exception as e:
        return f"<div style='color:red; border:1px solid red; padding:10px;'><b>Template Error:</b> {str(e)}</div>"

# --- APPLICATION VERSION ---
APP_VERSION = "7.5.0"
app.config['APP_VERSION'] = APP_VERSION
def format_rupiah(value):
    try:
        if value is None: return "0"
        # If it's already a string, clean it from "Rp", dots, and commas
        if isinstance(value, str):
            value = value.replace('Rp', '').replace('.', '').replace(',', '').strip()
        
        if not value or value == "": return "0"
        
        # Use Indonesian format: Dot for thousands
        return "{:,.0f}".format(float(value)).replace(',', '.')
    except (ValueError, TypeError):
        return value

UPDATE_URL = "https://mikrofun.site/updates/radius_version.json"

# Global cache for update check (shared across all users, not per-session)
_update_cache = {'info': None, 'last_check': 0}

def check_update():
    """Checks for updates (global-cached, non-blocking timeout)"""
    import requests
    try:
        # 1.5s connect + 1.5s read = max 3s total including DNS
        r = requests.get(UPDATE_URL, timeout=(1.5, 1.5))
        if r.status_code == 200:
            data = r.json()
            remote_version = data.get('version', APP_VERSION)
            
            # Semantic Version Comparison
            try:
                def parse_version(v):
                    return tuple(map(int, (v.split("."))))
                
                if parse_version(remote_version) > parse_version(APP_VERSION):
                    return {'available': True, 'version': remote_version, 'url': data.get('url', '#')}
            except Exception:
                # Fallback to simple string check if parsing fails but only if different
                if remote_version != APP_VERSION and remote_version > APP_VERSION:
                    return {'available': True, 'version': remote_version, 'url': data.get('url', '#')}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Update check failed: {e}")
        pass
    return None

@app.context_processor
def inject_app_settings():
    from web.database import execute_query
    from web.license_service import get_isp_name
    try:
        res = execute_query("SELECT setting_value FROM settings WHERE setting_key='company_logo'", fetch_one=True)
        app_logo = res['setting_value'] if res else None
    except:
        app_logo = None

    app_name = get_isp_name()
    return dict(app_name=app_name, app_logo=app_logo, app_version=APP_VERSION)

@app.context_processor
def inject_update_status():
    """Inject update availability into all templates. Uses global cache (not session)
    so only the first request every hour triggers the HTTP check."""
    import time
    
    now = time.time()
    
    # Check every hour using global cache (shared across all users)
    if _update_cache['info'] is None or (now - _update_cache['last_check'] > 3600):
        _update_cache['info'] = check_update()
        _update_cache['last_check'] = now
    
    update_info = _update_cache['info']
    
    # Validation: Ensure cached version is actually newer than current
    if update_info:
        cached_version = update_info.get('version', '')
        try:
            def parse_v(v): return tuple(map(int, (v.split("."))))
            if parse_v(cached_version) <= parse_v(APP_VERSION):
                _update_cache['info'] = None
                update_info = None
        except:
            if cached_version <= APP_VERSION:
                _update_cache['info'] = None
                update_info = None
        
    return dict(update_available=update_info)

# --- END APPLICATION VERSION ---

# Custom Jinja2 Filter untuk Format Mata Uang (Rupiah)
@app.template_filter('currency')
def format_currency(value):
    try:
        if value is None or str(value).strip() == '':
            return "Rp 0"
        # Konversi ke float lalu ke integer, lalu format dengan separator ribuan
        val = int(float(value))
        return f"Rp {val:,.0f}".replace(',', '.')
    except (ValueError, TypeError):
        return value

# Custom filter: price + PPN
@app.template_filter('price_total')
def format_price_total(price, tax_percent=0):
    """Display price including PPN: Rp 110.000"""
    try:
        if price is None:
            return "Rp 0"
        base = float(price)
        tax = float(tax_percent or 0)
        total = base + (base * tax / 100)
        return f"Rp {total:,.0f}".replace(',', '.')
    except (ValueError, TypeError):
        return price

# --- GLOBAL SECURITY HEADERS ---
@app.after_request
def add_security_headers(response):
    # Prevent Clickjacking (Except for Portal so it can be framed by MikroTik Hotspot)
    if not request.path.startswith('/portal/'):
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    # Prevent MIME sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Basic XSS protection (for older browsers)
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # Referrer policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # Strict Transport Security (HSTS)
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    # Content Security Policy (CSP)
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.jsdelivr.net cdn.tailwindcss.com; style-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com; font-src 'self' fonts.gstatic.com cdn.jsdelivr.net; img-src 'self' data: blob: http: https:;"
    return response

# --- GLOBAL CSRF PROTECTION ---
@app.before_request
def csrf_protect():
    if request.method in ["POST", "PUT", "DELETE"]:
        # Exclude paths that receive legitimate cross-origin requests
        exempt_prefixes = ('/api/', '/telegram/', '/portal/')
        if request.path.startswith(exempt_prefixes):
            return

        origin = request.headers.get('Origin')
        referer = request.headers.get('Referer')
        host = request.headers.get('X-Forwarded-Host', request.headers.get('Host'))
        
        if not host:
            return
            
        from urllib.parse import urlparse
        
        if origin:
            parsed = urlparse(origin)
            if parsed.netloc != host and parsed.netloc != host.split(':')[0]:
                from flask import abort
                abort(403, "CSRF Origin mismatch")
        elif referer:
            parsed = urlparse(referer)
            if parsed.netloc != host and parsed.netloc != host.split(':')[0]:
                from flask import abort
                abort(403, "CSRF Referer mismatch")
        else:
            # Block if no origin/referer is present on a state-changing web request
            from flask import abort
            abort(403, "CSRF protection: Missing Origin and Referer headers")

# Blueprints
from web.blueprints.auth import auth_bp
from web.blueprints.customers import customers_bp
from web.blueprints.mac_customers import mac_customers_bp
from web.blueprints.profiles import profiles_bp
from web.blueprints.routers import routers_bp
from web.blueprints.vouchers import vouchers_bp

app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(customers_bp, url_prefix='/customers')
app.register_blueprint(mac_customers_bp, url_prefix='/mac_customers')
app.register_blueprint(profiles_bp, url_prefix='/profiles')
app.register_blueprint(routers_bp, url_prefix='/routers')
app.register_blueprint(vouchers_bp, url_prefix='/vouchers')
from web.blueprints.olt import olt_bp
app.register_blueprint(olt_bp, url_prefix='/olt')
from web.blueprints.reports import reports_bp
app.register_blueprint(reports_bp, url_prefix='/reports')
from web.blueprints.notifications import notifications_bp
app.register_blueprint(notifications_bp, url_prefix='/notifications')
from web.blueprints.settings import settings_bp
app.register_blueprint(settings_bp, url_prefix='/settings')

from web.blueprints.landing_settings import landing_settings_bp
app.register_blueprint(landing_settings_bp, url_prefix='/landing-settings')

from web.blueprints.payment_settings import payment_settings_bp
app.register_blueprint(payment_settings_bp, url_prefix='/payment-settings')

from web.blueprints.api import api_bp
app.register_blueprint(api_bp, url_prefix='/api')

from web.blueprints.billing import billing_bp
app.register_blueprint(billing_bp, url_prefix='/billing')
from web.blueprints.client import client_bp
app.register_blueprint(client_bp, url_prefix='/client')
from web.blueprints.helpdesk import helpdesk_bp
app.register_blueprint(helpdesk_bp, url_prefix='/helpdesk')
from web.blueprints.odp import odp_bp
app.register_blueprint(odp_bp, url_prefix='/odp')

from web.blueprints.odc import odc_bp
app.register_blueprint(odc_bp, url_prefix='/odc')

from web.blueprints.users import users_bp
app.register_blueprint(users_bp, url_prefix='/users')
from web.blueprints.inventory import inventory_bp
app.register_blueprint(inventory_bp, url_prefix='/inventory')
from web.blueprints.cs import cs_bp
app.register_blueprint(cs_bp, url_prefix='/cs')

from web.blueprints.dispatch import dispatch_bp
app.register_blueprint(dispatch_bp, url_prefix='/dispatch')

from web.blueprints.tech import tech_bp
app.register_blueprint(tech_bp, url_prefix='/tech')

from web.blueprints.docs import docs_bp
app.register_blueprint(docs_bp, url_prefix='/docs')

from web.blueprints.logs import logs_bp
app.register_blueprint(logs_bp, url_prefix='/logs')

from web.blueprints.acs import acs_bp
app.register_blueprint(acs_bp, url_prefix='/acs')

from web.blueprints.portal import portal_bp
app.register_blueprint(portal_bp, url_prefix='/portal')
from web.blueprints.portal_settings import portal_settings_bp
app.register_blueprint(portal_settings_bp, url_prefix='/portal-settings')

from web.blueprints.wa_gateway import wa_gateway_bp
app.register_blueprint(wa_gateway_bp, url_prefix='/wa_gateway')

from web.blueprints.tunnels import tunnels_bp
app.register_blueprint(tunnels_bp, url_prefix='/tunnels')

from web.blueprints.telegram_bot import telegram_bot_bp
app.register_blueprint(telegram_bot_bp, url_prefix='/telegram_bot')

from web.blueprints.reseller_admin import reseller_admin_bp
app.register_blueprint(reseller_admin_bp, url_prefix='/reseller_admin')

from web.blueprints.reseller import reseller_bp
app.register_blueprint(reseller_bp, url_prefix='/reseller')

from web.blueprints.tools import tools_bp
app.register_blueprint(tools_bp, url_prefix='/tools')

from web.blueprints.mikhmon import mikhmon_bp
app.register_blueprint(mikhmon_bp, url_prefix='/mikhmon')

# --- Global Error Handler ---
@app.errorhandler(500)
def internal_error(error):
    try:
        from web.app_logger import log_error
        import traceback
        log_error(f'HTTP 500 Internal Server Error: {str(error)}',
                  exc=error if isinstance(error, Exception) else None)
    except Exception:
        pass
    return render_template('errors/500.html', error='Terjadi kesalahan internal. Tim teknis sudah diberitahu.'), 500

@app.errorhandler(Exception)
def unhandled_exception(e):
    # HTTPExceptions (403 CSRF block, 405 wrong method, 401, ...) carry their own
    # status and must pass through — swallowing them into a 500 hides the real
    # reason and logs deliberate rejections as crashes.
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e

    try:
        from web.app_logger import log_error
        log_error(f'Unhandled Exception: {type(e).__name__}: {str(e)}', exc=e)
    except Exception:
        pass
    return render_template('errors/500.html', error='Terjadi kesalahan internal. Tim teknis sudah diberitahu.'), 500

@app.errorhandler(404)
def not_found(e):
    return '', 404

@app.route('/landing-page')
def landing():
    import json
    from web.database import execute_query
    from flask import render_template_string
    
    # Get Company Settings
    company = {}
    
    # --- SENSITIVE DATA FILTERING ---
    # Only expose safe settings to the landing page and custom templates
    PUBLIC_SETTINGS_KEYS = [
        'app_name', 'company_name', 'company_address', 'company_phone', 'company_email',
        'company_logo', 'company_background', 'landing_page_template',
        'landing_page_custom_html', 'landing_page_packages', 'active_gateway'
    ]
    
    settings_rows = execute_query("SELECT setting_key, setting_value FROM settings", fetch=True) or []
    full_settings = {row['setting_key']: row['setting_value'] for row in settings_rows}
    
    # Filtered settings for template
    settings_dict = {k: v for k, v in full_settings.items() if k in PUBLIC_SETTINGS_KEYS or k.startswith('company_')}
    
    for key, val in settings_dict.items():
        if key.startswith('company_'):
            k = key.replace('company_', '')
            company[k] = val
            
    template_choice = settings_dict.get('landing_page_template', '1')
    custom_html = settings_dict.get('landing_page_custom_html', '')
    
    packages_json = settings_dict.get('landing_page_packages', '[]')
    try:
        packages = json.loads(packages_json)
        # Pre-format prices for safety so we don't need format_rupiah in sandbox
        for p in packages:
            if 'price' in p:
                p['formatted_price'] = format_rupiah(p['price'])
    except:
        packages = []
        
    if template_choice == 'custom':
        if not custom_html:
            custom_html = "<h1>Belum Ada Custom Template Yang Dikonfigurasi.</h1> <a href='/client/login'>Ke Portal Client</a>"
        return safe_render_template_string(custom_html, company=company, packages=packages)
    
    # Get Public Voucher Profiles
    voucher_profiles = execute_query("SELECT * FROM profiles WHERE type='voucher' AND price > 0 ORDER BY price ASC", fetch=True) or []
    
    # Get Active Gateway Info
    active_gateway = settings_dict.get('active_gateway', 'manual')
    tripay_channels = []
    duitku_channels = []
    
    if active_gateway in ['tripay', 'both']:
        from web.tripay_helper import TripayHelper
        tripay_channels = TripayHelper().get_payment_channels()
        
    if active_gateway in ['duitku', 'both']:
        from web.duitku_helper import DuitkuHelper
        # Duitku requires an amount to fetch channels, we'll use a default of 10000 
        # or the price of the cheapest voucher.
        min_price = 10000
        if voucher_profiles:
            min_price = int(min(v['price'] for v in voucher_profiles))
        duitku_channels, _error = DuitkuHelper().get_payment_methods(min_price)
        
    xendit_available = active_gateway in ('xendit', 'both')
        
    # Otherwise render standard themes 1, 2, 3
    if template_choice not in ['1', '2', '3']:
        template_choice = '1'

    try:
        return render_template(f'landing_{template_choice}.html', company=company, packages=packages, voucher_profiles=voucher_profiles, active_gateway=active_gateway, tripay_channels=tripay_channels, duitku_channels=duitku_channels, xendit_available=xendit_available, settings=settings_dict)
    except TemplateNotFound:
        # Built-in landing themes are optional; fall back instead of a 500.
        return redirect(url_for('client.login'))

@app.route('/')
def index():
    from web.database import execute_query
    
    # 1. First-Time Setup Check
    try:
        user_count = execute_query("SELECT COUNT(*) as count FROM users", fetch_one=True)
        if user_count and user_count['count'] == 0:
            return redirect(url_for('auth.setup'))
    except Exception:
        pass # If DB fails, let login catch it

    # 2. Login Check
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    if session.get('role') == 'technician':
        return redirect('/tech/dashboard')
    if session.get('role') == 'cs':
        return redirect(url_for('cs.dashboard'))
    if session.get('role') == 'reseller':
        return redirect(url_for('reseller.dashboard'))

    try:
        # Combine customer stats into single query
        cust_stats = execute_query(
            "SELECT "
            "COUNT(*) as total, "
            "SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) as active, "
            "SUM(CASE WHEN status IN ('expired','isolir') THEN 1 ELSE 0 END) as nunggak, "
            "SUM(CASE WHEN status='isolir' THEN 1 ELSE 0 END) as isolir "
            "FROM customers",
            fetch_one=True
        ) or {}
        total_cust = cust_stats.get('total') or 0
        active_cust = cust_stats.get('active') or 0
        nunggak_cust = cust_stats.get('nunggak') or 0
        isolir_cust = cust_stats.get('isolir') or 0

        # Router stats
        router_stats = execute_query(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status='online' THEN 1 ELSE 0 END) as online FROM routers",
            fetch_one=True
        ) or {}
        total_router = router_stats.get('total') or 0
        online_router = router_stats.get('online') or 0

        total_voucher = execute_query("SELECT COUNT(*) as c FROM vouchers WHERE status='unused'", fetch_one=True)
        total_voucher = total_voucher['c'] if total_voucher else 0

        monthly_income = execute_query(
            "SELECT SUM(amount) as total FROM payments WHERE status IN ('approved', 'PAID') "
            "AND MONTH(payment_date) = MONTH(CURRENT_DATE()) AND YEAR(payment_date) = YEAR(CURRENT_DATE())",
            fetch_one=True
        )
        est_omset = execute_query(
            "SELECT SUM(p.price) as total FROM customers c JOIN profiles p ON c.profile_id = p.id WHERE c.status='active'",
            fetch_one=True
        )
        pending_payments = execute_query("SELECT COUNT(*) as c FROM payments WHERE status = 'pending'", fetch_one=True)
        total_odp = execute_query("SELECT COUNT(*) as c FROM odps", fetch_one=True)

        pppoe_raw = execute_query("SELECT COUNT(*) as c FROM customers WHERE status='active' AND (static_ip IS NULL OR static_ip='')", fetch_one=True)
        static_raw = execute_query("SELECT COUNT(*) as c FROM customers WHERE status='active' AND static_ip IS NOT NULL AND static_ip!=''", fetch_one=True)

        online_pppoe_raw = execute_query(
            "SELECT COUNT(*) as c FROM active_sessions a "
            "JOIN customers c ON a.username = c.username "
            "WHERE (c.static_ip IS NULL OR c.static_ip='')", fetch_one=True
        )
        online_static_raw = execute_query(
            "SELECT COUNT(*) as c FROM active_sessions a "
            "JOIN customers c ON a.username = c.username "
            "WHERE c.static_ip IS NOT NULL AND c.static_ip!=''", fetch_one=True
        )

        tot_p = pppoe_raw['c'] if pppoe_raw else 0
        tot_s = static_raw['c'] if static_raw else 0
        on_p = online_pppoe_raw['c'] if online_pppoe_raw else 0
        on_s = online_static_raw['c'] if online_static_raw else 0

        chart_rows = execute_query(
            "SELECT DATE(created_at) as day, COALESCE(SUM(net_profit),0) as daily_net "
            "FROM income_ledger WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 6 DAY) "
            "GROUP BY DATE(created_at) ORDER BY day ASC", fetch=True
        ) or []
        chart_labels = [str(r['day'])[5:] for r in chart_rows]
        chart_values = [float(r['daily_net']) for r in chart_rows]

        source_rows = execute_query(
            "SELECT source_type, COALESCE(SUM(net_profit),0) as total "
            "FROM income_ledger WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) GROUP BY source_type",
            fetch=True
        ) or []
        source_labels = [r['source_type'].replace('_', ' ').title() for r in source_rows]
        source_values = [float(r['total']) for r in source_rows]

        recent_tx_raw = execute_query(
            "SELECT source_type, description, net_profit, created_at "
            "FROM income_ledger ORDER BY created_at DESC LIMIT 5", fetch=True
        ) or []
        recent_tx = []
        for tx in recent_tx_raw:
            ct = tx.get('created_at')
            recent_tx.append({
                'source_type': tx.get('source_type'),
                'description': tx.get('description'),
                'net_profit': tx.get('net_profit'),
                'created_at': ct.strftime('%Y-%m-%d %H:%M') if hasattr(ct, 'strftime') else str(ct or '-')
            })

        stats = {
            'total_customers': total_cust,
            'active_customers': active_cust,
            'nunggak_customers': nunggak_cust,
            'isolir_customers': isolir_cust,
            'total_routers': total_router,
            'online_routers': online_router,
            'available_vouchers': total_voucher,
            'monthly_income': monthly_income['total'] if monthly_income and monthly_income['total'] else 0,
            'est_omset': est_omset['total'] if est_omset and est_omset['total'] else 0,
            'pending_payments': pending_payments['c'] if pending_payments else 0,
            'total_odp': total_odp['c'] if total_odp else 0,
            'tot_p': tot_p, 'on_p': on_p, 'off_p': max(0, tot_p - on_p),
            'tot_s': tot_s, 'on_s': on_s, 'off_s': max(0, tot_s - on_s),
            'chart_labels': chart_labels,
            'chart_values': chart_values,
            'source_labels': source_labels,
            'source_values': source_values,
            'recent_tx': recent_tx
        }
    except Exception as e:
        print(f"[dashboard] Stats error: {e}")
        stats = {
            'total_customers': 0, 'active_customers': 0, 'nunggak_customers': 0, 'isolir_customers': 0,
            'total_routers': 0, 'online_routers': 0, 'available_vouchers': 0,
            'monthly_income': 0, 'est_omset': 0, 'pending_payments': 0, 'total_odp': 0,
            'tot_p': 0, 'on_p': 0, 'off_p': 0, 'tot_s': 0, 'on_s': 0, 'off_s': 0,
            'chart_labels': [], 'chart_values': [], 'source_labels': [], 'source_values': [],
            'recent_tx': []
        }

    return render_template('dashboard.html', stats=stats, title='Dashboard')

# ── AI NOC API ──────────────────────────────────────
def _ai_admin_guard():
    """AI NOC exposes network/customer/billing data and can mutate the system,
    so it is restricted to administrators, not every logged-in role."""
    if not session.get('logged_in'):
        return {"error": "unauthorized"}, 401
    if session.get('role') != 'admin':
        return {"error": "forbidden"}, 403
    return None

@app.route('/api/ai/diagnose', methods=['POST'])
def api_ai_diagnose():
    """POST JSON: {"symptom": "...", "username": "(optional)"} """
    denied = _ai_admin_guard()
    if denied:
        return denied

    from ai_noc.diagnosis import diagnose
    try:
        data = request.get_json(force=True)
        symptom = data.get('symptom', '').strip()
        username = data.get('username', '').strip() or None
        if not symptom:
            return {"error": "symptom required"}, 400
        result = diagnose(symptom, username=username)
        return result, 200
    except Exception as e:
        return {"error": str(e)}, 500

@app.route('/api/ai/wa-reply', methods=['POST'])
def api_ai_wa_reply():
    """
    Baileys forwards incoming WA here. AI checks customer context and auto-replies.
    POST: {"sender": "62812xxx", "text": "pak internet saya mati"}
    """
    from web.database import execute_query
    from ai_noc.deepseek_client import chat as ai_chat
    from web.wa_helper import send_wa

    api_key = request.headers.get('X-API-Key', '')
    wa_api_key = os.environ.get('WA_API_KEY')
    if not wa_api_key:
        return {"error": "WA_API_KEY not configured"}, 503
    if api_key != wa_api_key:
        return {"error": "unauthorized"}, 401

    try:
        data = request.get_json(force=True)
        sender = data.get('sender', '')
        text = data.get('text', '').strip()

        if not sender or not text:
            return {"error": "sender and text required"}, 400

        # Find customer by phone
        customer = execute_query(
            """SELECT c.username, c.full_name, c.status, c.due_date,
                      p.name AS profile, p.rate_limit
               FROM customers c LEFT JOIN profiles p ON c.profile_id = p.id
               WHERE REPLACE(REPLACE(c.phone, '+', ''), ' ', '') LIKE %s
               LIMIT 1""",
            (f"%{sender[-8:]}",), fetch_one=True
        )

        if not customer:
            # Unknown number, AI still replies politely
            reply = ai_chat(
                "Anda CS MikroFun ISP. Orang ini bukan pelanggan terdaftar. "
                "Balas singkat, tanya keperluan, tawarkan daftar. Maks 100 kata. Bahasa Indonesia.",
                f"Nomor: {sender}\nPesan: {text}"
            )
            if reply:
                send_wa(sender, reply)
            return {"status": "replied", "customer": None}, 200

        # Build context for AI
        ctx = (
            f"Pelanggan: {customer['full_name']} ({customer['username']})\n"
            f"Status: {customer['status']}, Due: {customer['due_date']}\n"
            f"Paket: {customer['profile']} ({customer['rate_limit']})\n"
            f"Pesan pelanggan: {text}"
        )

        reply = ai_chat(
            "Anda CS MikroFun ISP. Jawab pelanggan dengan cepat dan membantu. "
            "Jika internet mati — cek status (isolir/jatuh tempo/aktif). "
            "Jika billing — jelaskan cara bayar (TriPay, transfer bank). "
            "Jika lainnya — bantu semampunya. Maks 150 kata. Bahasa Indonesia.",
            ctx
        )

        if reply:
            send_wa(sender, reply)
        return {"status": "replied", "customer": customer['username']}, 200

    except Exception as e:
        return {"error": str(e)}, 500

@app.route('/api/ai/health')
def api_ai_health():
    """Check if AI NOC module is functional."""
    denied = _ai_admin_guard()
    if denied:
        return denied

    try:
        from ai_noc.deepseek_client import chat
        return {"status": "ok", "key_loaded": bool(os.environ.get("DEEPSEEK_API_KEY"))}, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@app.route('/api/ai/ask', methods=['POST'])
def api_ai_ask():
    """General AI ask — natural language + ability to create (profiles, customers, vouchers)."""
    denied = _ai_admin_guard()
    if denied:
        return denied

    from web.database import execute_query
    from ai_noc.deepseek_client import chat as ai_chat

    try:
        data = request.get_json(force=True)
        question = data.get('question', '').strip()
        if not question:
            return {"error": "question required"}, 400

        # ── Collect ALL system context for the AI ──
        profiles  = execute_query("SELECT id, name, rate_limit, price, type, validity, validity_unit FROM profiles ORDER BY name", fetch=True) or []
        routers   = execute_query("SELECT id, name, status, vpn_ip, ip_address, api_user, api_password FROM routers ORDER BY name", fetch=True) or []

        cust_active = execute_query("SELECT COUNT(*) as c FROM customers WHERE status='active'", fetch_one=True)
        cust_isolir = execute_query("SELECT COUNT(*) as c FROM customers WHERE status='isolated'", fetch_one=True)
        users_online = execute_query("SELECT COUNT(*) as c FROM active_sessions", fetch_one=True)
        routers_off = sum(1 for r in routers if r['status'] == 'offline')

        # Payments today
        pay_today = execute_query(
            "SELECT COALESCE(SUM(amount),0) as total, COUNT(*) as cnt FROM payments WHERE DATE(created_at)=CURDATE() AND status='paid'",
            fetch_one=True
        )
        pay_month = execute_query(
            "SELECT COALESCE(SUM(amount),0) as total, COUNT(*) as cnt FROM payments WHERE YEAR(created_at)=YEAR(CURDATE()) AND MONTH(created_at)=MONTH(CURDATE()) AND status='paid'",
            fetch_one=True
        )

        # Vouchers
        vouch_active = execute_query("SELECT COUNT(*) as c FROM vouchers WHERE status='active'", fetch_one=True)
        vouch_used = execute_query("SELECT COUNT(*) as c FROM vouchers WHERE status='used'", fetch_one=True)

        # Per-user data (top traffic, online, due dates)
        top_traffic = execute_query(
            "SELECT username, ROUND(SUM(acctoutputoctets+acctinputoctets)/1048576,1) AS mb "
            "FROM radacct_snapshots WHERE snapshot_time >= DATE_SUB(NOW(), INTERVAL 1 HOUR) "
            "GROUP BY username ORDER BY mb DESC LIMIT 5", fetch=True) or []

        online_users = execute_query(
            "SELECT a.username, a.framedipaddress, a.nas_ip, "
            "TIMESTAMPDIFF(MINUTE, a.updated_at, NOW()) AS idle_min "
            "FROM active_sessions a ORDER BY a.updated_at DESC LIMIT 10", fetch=True) or []

        due_soon = execute_query(
            "SELECT name, username, due_date, DATEDIFF(due_date, CURDATE()) AS days_left "
            "FROM customers WHERE status='active' AND due_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 7 DAY) "
            "ORDER BY due_date LIMIT 10", fetch=True) or []

        recent_pay = execute_query(
            "SELECT c.name, p.amount, p.created_at FROM payments p "
            "JOIN customers c ON p.customer_id=c.id WHERE p.status='paid' "
            "ORDER BY p.created_at DESC LIMIT 5", fetch=True) or []

        # ── Eager MikroTik data (light commands from online routers) ──
        mikrotik_ctx = ""
        for r in routers:
            if r['status'] != 'online':
                continue
            try:
                from web.mikrotik_api import MikrotikApi
                ip = r.get('vpn_ip') or r.get('ip_address')
                if not ip:
                    continue
                api = MikrotikApi(ip, timeout=3)
                api.login(r.get('api_user', 'admin'), r.get('api_password', ''))
                res = api.query(['/system/resource/print'])
                if res:
                    s = res[0]
                    mikrotik_ctx += (
                        f"  {r['name']} ({ip}): ROS {s.get('version','?')}, "
                        f"CPU {s.get('cpu-load','?')}%, "
                        f"RAM {int(s.get('free-memory',0))//1048576}MB free, "
                        f"uptime {s.get('uptime','?')}\n"
                    )
            except Exception:
                pass
        if mikrotik_ctx:
            mikrotik_ctx = "DATA MIKROTIK (real-time):\n" + mikrotik_ctx + "\n"
        # ── End MikroTik context ──

        profile_list = "\n".join(
            f"  - {p['name']} ({p['type']}): {p['rate_limit']}, Rp{p['price']:,}, {p['validity']} {p['validity_unit']}"
            for p in profiles
        )
        router_list = "\n".join(f"  - {r['name']} ({r['status']})" for r in routers)

        # ── Build data-dense context string ──
        top_traffic_str = "\n".join(
            f"    {t['username']}: {t['mb']}MB" for t in top_traffic) if top_traffic else "    (tidak ada)"

        online_str = "\n".join(
            f"    {o['username']} @ {o['framedipaddress']} (NAS: {o['nas_ip']}, idle: {o['idle_min']}m)"
            for o in online_users) if online_users else "    (tidak ada)"

        due_str = "\n".join(
            f"    {d['username']}: {d['due_date']} ({d['days_left']} hari lagi)"
            for d in due_soon) if due_soon else "    (tidak ada)"

        pay_str = "\n".join(
            f"    {p['name']} Rp{p['amount']:,.0f} ({p['created_at']})"
            for p in recent_pay) if recent_pay else "    (tidak ada)"

        data_ctx = (
            f"PELANGGAN: {cust_active.get('c',0) if cust_active else 0} aktif"
            f", {cust_isolir.get('c',0) if cust_isolir else 0} isolir"
            f", {users_online.get('c',0) if users_online else 0} online\n"
            f"ROUTER: {len(routers)} total, {routers_off} offline\n"
            f"PAKET: {len(profiles)} tersedia\n"
            f"VOUCHER: {vouch_active.get('c',0) if vouch_active else 0} aktif"
            f", {vouch_used.get('c',0) if vouch_used else 0} terpakai\n"
            f"KEUANGAN: hari ini Rp{pay_today.get('total',0) if pay_today else 0:,.0f}"
            f" ({pay_today.get('cnt',0) if pay_today else 0} tx), "
            f"bulan ini Rp{pay_month.get('total',0) if pay_month else 0:,.0f}"
            f" ({pay_month.get('cnt',0) if pay_month else 0} tx)\n"
            f"TOP TRAFIK (1 jam):\n{top_traffic_str}\n"
            f"USER ONLINE:\n{online_str}\n"
            f"JATUH TEMPO (7 hari):\n{due_str}\n"
            f"PEMBAYARAN TERBARU:\n{pay_str}\n"
            f"{mikrotik_ctx}"
        )

        system = (
            "Anda AI Operator MikroFun ISP. Anda punya akses penuh ke data real-time.\n\n"
            f"DATA REAL-TIME:\n{data_ctx}\n"
            "HAL YANG BISA ANDA LAKUKAN:\n"
            "- Jawab pertanyaan PAKAI data di atas (jumlah pelanggan, keuangan, router, dll)\n"
            "- Buat paket/pelanggan/voucher (CREATE_PROFILE, CREATE_CUSTOMER, CREATE_VOUCHER)\n"
            "- Baca data MikroTik via API (READ_MIKROTIK) — perintah RouterOS:\n"
            "  /interface/print .proplist=name,type,disabled,comment,running\n"
            "  /ppp/active/print\n"
            "  /ip/hotspot/active/print\n"
            "  /ip/dhcp-server/lease/print\n"
            "  /queue/simple/print\n"
            "  /log/print\n"
            "  /system/resource/print\n\n"
            "ATURAN:\n"
            "- Ditanya data → JAWAB pakai angka dari DATA REAL-TIME di atas.\n"
            "- Data tidak ada → bilang 'saya belum punya data itu', jangan mengarang.\n"
            "- Diminta BUAT → kumpulkan field, kalau lengkap balas:\n"
            "  [ACTION]\n"
            "  {\"action\": \"CREATE_...\", \"params\": {...}}\n"
            "  [/ACTION]\n"
            "- Bahasa Indonesia, ringkas.\n\n"
            f"DAFTAR PAKET:\n{profile_list}\n\n"
            f"DAFTAR ROUTER:\n{router_list}"
        )

        # Build conversation prefix from history
        history = data.get('history', [])
        history_prefix = ""
        if history:
            lines = []
            for h in history[-10:]:  # max 10 messages
                role = "Operator" if h.get('role') == 'user' else "AI"
                lines.append(f"{role}: {h.get('content', '')}")
            history_prefix = "RIWAYAT PERCAKAPAN:\n" + "\n".join(lines) + "\n\n"

        answer = ai_chat(system, f"{history_prefix}Pesan operator: {question}", max_tokens=800)
        return {"answer": answer or "AI tidak tersedia (API key belum diset?)"}, 200

    except Exception as e:
        return {"error": str(e)}, 500


@app.route('/api/ai/execute', methods=['POST'])
def api_ai_execute():
    """Execute AI-suggested action: create profile, customer, or voucher."""
    denied = _ai_admin_guard()
    if denied:
        return denied

    from web.database import execute_query
    from werkzeug.security import generate_password_hash

    try:
        data = request.get_json(force=True)
        action = data.get('action', '')
        params = data.get('params', {})

        if action == 'CREATE_PROFILE':
            p = params
            required = ['name', 'rate_limit', 'price', 'type', 'validity', 'validity_unit']
            missing = [f for f in required if not p.get(f)]
            if missing:
                return {"error": f"Field kurang: {', '.join(missing)}"}, 400

            execute_query(
                "INSERT INTO profiles (name, rate_limit, price, type, validity, validity_unit) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (p['name'], p['rate_limit'], p['price'], p['type'], p['validity'], p['validity_unit'])
            )
            return {"ok": True, "message": f"Paket '{p['name']}' berhasil dibuat"}, 200

        elif action == 'CREATE_CUSTOMER':
            p = params
            required = ['name', 'username', 'password', 'profile_name']
            missing = [f for f in required if not p.get(f)]
            if missing:
                return {"error": f"Field kurang: {', '.join(missing)}"}, 400

            # Resolve profile name to ID
            prof = execute_query("SELECT id FROM profiles WHERE name=%s", (p['profile_name'],), fetch_one=True)
            if not prof:
                return {"error": f"Paket '{p['profile_name']}' tidak ditemukan"}, 400

            hashed = generate_password_hash(p['password'])
            execute_query(
                "INSERT INTO customers (name, username, password, service_type, profile_id, phone, address, due_date, status, billing_type) "
                "VALUES (%s,%s,%s,'pppoe',%s,%s,%s,%s,'active','prepaid')",
                (p['name'], p['username'], hashed, prof['id'],
                 p.get('phone', ''), p.get('address', ''), p.get('due_date'))
            )
            return {"ok": True, "message": f"Pelanggan '{p['name']}' ({p['username']}) berhasil dibuat"}, 200

        elif action == 'CREATE_VOUCHER':
            p = params
            required = ['code', 'profile_name', 'duration']
            missing = [f for f in required if not p.get(f)]
            if missing:
                return {"error": f"Field kurang: {', '.join(missing)}"}, 400

            prof = execute_query("SELECT id FROM profiles WHERE name=%s AND type='voucher'", (p['profile_name'],), fetch_one=True)
            if not prof:
                return {"error": f"Paket voucher '{p['profile_name']}' tidak ditemukan"}, 400

            execute_query(
                "INSERT INTO vouchers (code, profile_id, duration, status, created_at) "
                "VALUES (%s,%s,%s,'active',NOW())",
                (p['code'], prof['id'], p['duration'])
            )
            return {"ok": True, "message": f"Voucher '{p['code']}' berhasil dibuat"}, 200

        elif action == 'READ_MIKROTIK':
            p = params
            required = ['router', 'command']
            missing = [f for f in required if not p.get(f)]
            if missing:
                return {"error": f"Field kurang: {', '.join(missing)}"}, 400

            # This action is read-only by contract: refuse anything that could
            # add/set/remove state on the router, even if the model asks for it.
            command = str(p['command']).strip()
            if not command.endswith('/print') and '/print ' not in command:
                return {"error": "READ_MIKROTIK hanya mengizinkan perintah '/print'"}, 400

            rtr = execute_query(
                "SELECT vpn_ip, ip_address, api_user, api_password FROM routers WHERE name=%s LIMIT 1",
                (p['router'],), fetch_one=True
            )
            if not rtr:
                return {"error": f"Router '{p['router']}' tidak ditemukan"}, 400

            ip = rtr.get('vpn_ip') or rtr.get('ip_address')
            if not ip:
                return {"error": f"Router '{p['router']}' tidak punya IP"}, 400

            from web.mikrotik_api import MikrotikApi
            api = MikrotikApi(ip)
            if not api.login(rtr.get('api_user', 'admin'), rtr.get('api_password', '')):
                return {"error": f"Login ke router {ip} gagal"}, 400
            result = api.query([command])
            return {"ok": True, "result": result}, 200

        return {"error": f"Unknown action: {action}"}, 400

    except Exception as e:
        return {"error": str(e)}, 500

@app.route('/ai-chat')
def ai_chat_page():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    return render_template('ai_chat.html', title='AI NOC Chat')

@app.context_processor
def inject_premium_status():
    from web.license_service import is_premium
    return dict(is_premium=is_premium())

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
