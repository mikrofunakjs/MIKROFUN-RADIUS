"""Reseller Portal Blueprint (Mobile First UI)"""
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
import string, random, datetime
from web.database import execute_query
from web.mikrotik_api import MikrotikApi

reseller_bp = Blueprint('reseller', __name__)

def get_isp_name():
    row = execute_query("SELECT setting_value FROM settings WHERE setting_key='company_name'", fetch_one=True)
    return row['setting_value'] if row else 'MikroFun'

@reseller_bp.context_processor
def inject_reseller_globals():
    """Automatically inject isp_name and theme color into all reseller templates (whitelabel)"""
    row_name = execute_query("SELECT setting_value FROM settings WHERE setting_key='company_name'", fetch_one=True)
    isp_name = row_name['setting_value'] if row_name else 'MikroFun'
    row_color = execute_query("SELECT setting_value FROM settings WHERE setting_key='reseller_theme_color'", fetch_one=True)
    theme_color = row_color['setting_value'] if row_color else '#4f46e5'
    return dict(isp_name=isp_name, reseller_theme_color=theme_color)
def reseller_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in') or session.get('role') != 'reseller':
            flash('Silakan login terlebih dahulu.', 'error')
            return redirect(url_for('reseller.login'))
        return f(*args, **kwargs)
    return decorated_function

@reseller_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Already logged in as reseller -> go to dashboard
    if session.get('logged_in') and session.get('role') == 'reseller':
        return redirect(url_for('reseller.dashboard'))

    isp_name = get_isp_name()

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = execute_query(
            "SELECT * FROM users WHERE username=%s AND role='reseller'",
            (username,), fetch_one=True
        )
        if user:
            from werkzeug.security import check_password_hash
            is_valid = False
            if ':' in user.get('password', ''):
                try:
                    is_valid = check_password_hash(user['password'], password)
                except Exception:
                    is_valid = (user['password'] == password)
            else:
                is_valid = (user['password'] == password)
            if is_valid:
                session['logged_in'] = True
                session['username'] = user['username']
                session['user_id'] = user['id']
                session['role'] = 'reseller'
                session.permanent = True
                return redirect(url_for('reseller.dashboard'))
        flash('Username atau password salah, atau akun bukan Mitra.', 'error')

    return render_template('reseller/login.html', isp_name=isp_name)

@reseller_bp.route('/logout')
def logout_mitra():
    session.clear()
    return redirect(url_for('reseller.login'))

def get_reseller_data():
    """Helper to get current balance and discount"""
    user = execute_query("SELECT balance, discount_percent FROM users WHERE id=%s", (session['user_id'],), fetch_one=True)
    if user:
        return float(user['balance']), int(user['discount_percent'])
    return 0.0, 0

@reseller_bp.route('/dashboard')
@reseller_required
def dashboard():
    balance, discount_percent = get_reseller_data()
    
    # Stats
    stats = execute_query(
        "SELECT COUNT(*) as total_sold, COALESCE(SUM(price - buy_price), 0) as profit "
        "FROM vouchers WHERE reseller_id=%s AND status != 'unused'", 
        (session['user_id'],), fetch_one=True
    )
    
    # Recent Purchases by this reseller
    recent = execute_query(
        "SELECT v.*, p.name as profile_name FROM vouchers v "
        "LEFT JOIN profiles p ON v.profile_id = p.id "
        "WHERE v.reseller_id=%s ORDER BY v.created_at DESC LIMIT 5",
        (session['user_id'],), fetch=True
    ) or []
    
    return render_template(
        'reseller/dashboard.html', 
        balance=balance, 
        discount_percent=discount_percent,
        total_sold=stats['total_sold'] if stats else 0,
        total_profit=stats['profit'] if stats else 0,
        recent_vouchers=recent
    )

@reseller_bp.route('/buy', methods=['GET', 'POST'])
@reseller_required
def buy():
    balance, discount_percent = get_reseller_data()
    
    if request.method == 'POST':
        profile_id = request.form.get('profile_id')
        if not profile_id:
            flash('Pilih profil terlebih dahulu.', 'error')
            return redirect(url_for('reseller.buy'))

        # Ambil data profil voucher
        profile = execute_query(
            "SELECT * FROM profiles WHERE id=%s AND type='voucher' AND price > 0",
            (profile_id,), fetch_one=True
        )
        if not profile:
            flash('Profil voucher tidak valid atau tidak dijual.', 'error')
            return redirect(url_for('reseller.buy'))
            
        normal_price = float(profile['price'])
        buy_price = round(normal_price - (normal_price * discount_percent / 100), 2)
        
        # Cek saldo cukup
        if buy_price > balance:
            flash(f'Saldo tidak cukup (Sisa: Rp {balance:,.0f}). Butuh Rp {buy_price:,.0f}', 'error')
            return redirect(url_for('reseller.buy'))
        
        # Generate kode voucher unik
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        # Pastikan kode belum ada
        while execute_query("SELECT id FROM vouchers WHERE code=%s", (code,), fetch_one=True):
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        try:
            new_balance = balance - buy_price
            duration_hours = profile.get('validity') or 24
            
            # Simpan voucher ke database (RADIUS system — tidak perlu Mikrotik API)
            execute_query(
                "INSERT INTO vouchers (code, profile_id, duration_hours, price, status, created_by, reseller_id, buy_price) "
                "VALUES (%s, %s, %s, %s, 'unused', %s, %s, %s)",
                (code, profile['id'], duration_hours, profile['price'],
                 session.get('username'), session['user_id'], buy_price)
            )
            
            # Potong saldo mitra
            execute_query("UPDATE users SET balance=%s WHERE id=%s", (new_balance, session['user_id']))
            
            # Catat transaksi
            execute_query(
                "INSERT INTO reseller_transactions "
                "(reseller_id, type, amount, description, balance_before, balance_after) "
                "VALUES (%s, 'purchase', %s, %s, %s, %s)",
                (session['user_id'], buy_price,
                 f"Generate Voucher: {profile['name']}", balance, new_balance)
            )

            # ── FINANCE LEDGER: catat margin voucher mitra ─────────────────
            try:
                from web.finance_helper import record_mitra_voucher
                record_mitra_voucher(profile, session.get('username', '-'), buy_price, code)
            except Exception as _fe:
                print(f"[finance] warn: {_fe}")
            # ──────────────────────────────────────────────────────────────

            flash(f'✅ Voucher {code} berhasil dicetak! Saldo terpotong Rp {buy_price:,.0f}', 'success')
            return redirect(url_for('reseller.history'))
            
        except Exception as e:
            flash(f'Terjadi kesalahan: {str(e)}', 'error')
            return redirect(url_for('reseller.buy'))

    profiles = execute_query("SELECT * FROM profiles WHERE type='voucher' AND price > 0 ORDER BY price", fetch=True) or []
    
    return render_template(
        'reseller/buy.html',
        profiles=profiles,
        balance=balance,
        discount_percent=discount_percent
    )

@reseller_bp.route('/topup', methods=['GET', 'POST'])
@reseller_required
def topup():
    balance, discount_percent = get_reseller_data()
    
    if request.method == 'POST':
        amount = int(request.form.get('amount', 0))
        method_code = request.form.get('method_code')
        
        if amount < 10000:
            flash('Minimal Top-Up Rp 10.000', 'error')
            return redirect(url_for('reseller.topup'))
            
        if not method_code:
            flash('Pilih metode pembayaran.', 'error')
            return redirect(url_for('reseller.topup'))
            
        # Get Active Gateway from settings
        settings_rows = execute_query("SELECT setting_key, setting_value FROM settings", fetch=True)
        settings = {s['setting_key']: s['setting_value'] for s in settings_rows}
        active_gateway = settings.get('active_gateway', 'manual')

        if method_code.startswith('TRIPAY_'):
            # Handle Tripay Topup
            method_code = method_code.replace('TRIPAY_', '')
            from web.tripay_helper import TripayHelper
            tripay = TripayHelper()
            
            import time
            reseller_id = session['user_id']
            merchant_ref = f"RTOP-{int(time.time())}-{reseller_id}"
            
            # Tripay requires customer details
            customer_name = session['username']
            customer_email = f"{customer_name}@reseller.local"
            customer_phone = '08123456789'
            
            # Get real data if possible
            res_info = execute_query("SELECT email, phone FROM users WHERE id=%s", (reseller_id,), fetch_one=True)
            if res_info:
                if res_info.get('email'): customer_email = res_info['email']
                if res_info.get('phone'): customer_phone = res_info['phone']

            customer_data = {
                'id': reseller_id,
                'first_name': customer_name,
                'email': customer_email,
                'phone': customer_phone
            }
            order_items = [{'name': 'Top-Up Saldo Mitra', 'price': amount, 'quantity': 1}]
            return_url = f"{request.url_root.rstrip('/')}/reseller/dashboard"
            
            data, error = tripay.request_transaction(method_code, amount, customer_data, order_items, return_url=return_url, merchant_ref=merchant_ref)
            if error or not data:
                flash(f'Gagal membuat transaksi Tripay: {error}', 'error')
                return redirect(url_for('reseller.topup'))
                
            execute_query(
                "INSERT INTO payments (amount, payment_channel, external_ref, checkout_url, status, created_at, payment_type, reseller_id) "
                "VALUES (%s, %s, %s, %s, 'pending', NOW(), 'reseller_topup', %s)",
                (amount, method_code, merchant_ref, data['checkout_url'], reseller_id)
            )
            return redirect(data['checkout_url'])

        else:
            # Handle Duitku Topup (default or explicit)
            from web.duitku_helper import DuitkuHelper
            duitku = DuitkuHelper()
            
            import time
            reseller_id = session['user_id']
            username = session['username']
            merchant_ref = f"RTOP-{int(time.time())}-{reseller_id}"
            
            customer_data = {
                'id': str(reseller_id),
                'first_name': username,
                'email': f"{username}@reseller.local",
                'phone': '08123456789'
            }
            
            res_info = execute_query("SELECT email, phone FROM users WHERE id=%s", (reseller_id,), fetch_one=True)
            if res_info:
                if res_info.get('email'): customer_data['email'] = res_info['email']
                if res_info.get('phone'): customer_data['phone'] = res_info['phone']
            
            order_items = [{'name': 'Top-Up Saldo Mitra', 'price': amount, 'quantity': 1}]
            
            callback_url = f"{request.url_root.rstrip('/')}/api/callback/duitku"
            return_url = f"{request.url_root.rstrip('/')}/reseller/dashboard"
            
            # FIXED: Correct argument order (payment_method, amount, product_details, customer_details, ...)
            data, error = duitku.request_transaction(method_code, amount, order_items, customer_data, callback_url, return_url, merchant_ref)
            
            if error or not data:
                flash(f'Gagal membuat transaksi Duitku: {error}', 'error')
                return redirect(url_for('reseller.topup'))
                
            execute_query(
                "INSERT INTO payments (amount, payment_channel, external_ref, checkout_url, status, created_at, payment_type, reseller_id) "
                "VALUES (%s, %s, %s, %s, 'pending', NOW(), 'reseller_topup', %s)",
                (amount, data['payment_method'], data['merchant_order_id'], data['checkout_url'], reseller_id)
            )
            return redirect(data['checkout_url'])
        
    # GET method
    settings_rows = execute_query("SELECT setting_key, setting_value FROM settings", fetch=True)
    settings = {s['setting_key']: s['setting_value'] for s in settings_rows}
    active_gateway = settings.get('active_gateway', 'manual')
    
    tripay_channels = []
    if active_gateway in ['tripay', 'both']:
        from web.tripay_helper import TripayHelper
        tripay = TripayHelper()
        try:
            tripay_channels = tripay.get_payment_channels() or []
        except:
            pass

    return render_template('reseller/topup.html', balance=balance, active_gateway=active_gateway, tripay_channels=tripay_channels, settings=settings)

@reseller_bp.route('/topup/midtrans-token', methods=['POST'])
@reseller_required
def midtrans_token():
    amount = request.json.get('amount')
    if not amount or int(amount) < 10000:
        return {'error': 'Minimal topup Rp 10.000'}, 400
        
    reseller_id = session['user_id']
    username = session['username']
    
    import time
    order_id = f"RTOP-MID-{reseller_id}-{int(time.time())}"
    
    from web.midtrans_helper import MidtransHelper
    helper = MidtransHelper()
    
    customer_data = {
        'first_name': username,
        'email': f"{username}@reseller.local",
        'phone': '08123456789'
    }
    
    res_info = execute_query("SELECT email, phone FROM users WHERE id=%s", (reseller_id,), fetch_one=True)
    if res_info:
        if res_info.get('email'): customer_data['email'] = res_info['email']
        if res_info.get('phone'): customer_data['phone'] = res_info['phone']
        
    token_data, error = helper.get_snap_token(order_id, amount, customer_data)
    
    if token_data and 'token' in token_data:
        execute_query(
            "INSERT INTO payments (amount, payment_channel, external_ref, status, created_at, payment_type, reseller_id) "
            "VALUES (%s, 'MIDTRANS', %s, 'pending', NOW(), 'reseller_topup', %s)",
            (amount, order_id, reseller_id)
        )
        return {'token': token_data.get('token'), 'redirect_url': token_data.get('redirect_url')}
        
    return {'error': error or 'Gagal mendapatkan token Midtrans'}, 500

@reseller_bp.route('/bulk_buy', methods=['GET', 'POST'])
@reseller_required
def bulk_buy():
    balance, discount_percent = get_reseller_data()
    
    if request.method == 'POST':
        profile_id = request.form.get('profile_id')
        qty = int(request.form.get('qty', 1))
        
        if not profile_id or qty <= 0:
            flash('Data tidak lengkap.', 'error')
            return redirect(url_for('reseller.bulk_buy'))

        if qty > 100:
            flash('Maksimal 100 voucher sekali cetak.', 'error')
            return redirect(url_for('reseller.bulk_buy'))

        profile = execute_query(
            "SELECT * FROM profiles WHERE id=%s AND type='voucher' AND price > 0",
            (profile_id,), fetch_one=True
        )
        if not profile:
            flash('Profil voucher tidak valid.', 'error')
            return redirect(url_for('reseller.bulk_buy'))
            
        unit_price = float(profile['price'])
        unit_buy_price = round(unit_price - (unit_price * discount_percent / 100), 2)
        total_cost = unit_buy_price * qty
        
        if total_cost > balance:
            flash(f'Saldo tidak cukup. Butuh Rp {total_cost:,.0f}', 'error')
            return redirect(url_for('reseller.bulk_buy'))
        
        try:
            codes = []
            for _ in range(qty):
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
                while execute_query("SELECT id FROM vouchers WHERE code=%s", (code,), fetch_one=True):
                    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
                
                duration_hours = profile.get('validity') or 24
                execute_query(
                    "INSERT INTO vouchers (code, profile_id, duration_hours, price, status, created_by, reseller_id, buy_price) "
                    "VALUES (%s, %s, %s, %s, 'unused', %s, %s, %s)",
                    (code, profile['id'], duration_hours, profile['price'],
                     session.get('username'), session['user_id'], unit_buy_price)
                )
                codes.append(code)
            
            new_balance = balance - total_cost
            execute_query("UPDATE users SET balance=%s WHERE id=%s", (new_balance, session['user_id']))
            
            execute_query(
                "INSERT INTO reseller_transactions "
                "(reseller_id, type, amount, description, balance_before, balance_after) "
                "VALUES (%s, 'purchase', %s, %s, %s, %s)",
                (session['user_id'], total_cost,
                 f"Bulk Generate {qty} Vouchers: {profile['name']}", balance, new_balance)
            )

            flash(f'✅ Berhasil mencetak {qty} voucher!', 'success')
            # Redirect to advanced print view for these new vouchers
            return redirect(url_for('reseller.print_vouchers', codes=','.join(codes)))
            
        except Exception as e:
            flash(f'Terjadi kesalahan: {str(e)}', 'error')
            
    profiles = execute_query("SELECT * FROM profiles WHERE type='voucher' AND price > 0 ORDER BY price", fetch=True) or []
    return render_template('reseller/bulk_buy.html', profiles=profiles, balance=balance)

@reseller_bp.route('/thermal_print')
@reseller_required
def thermal_print():
    codes_str = request.args.get('codes', '')
    if not codes_str:
        return "No codes provided", 400
        
    codes = codes_str.split(',')
    format_strings = ','.join(['%s'] * len(codes))
    vouchers = execute_query(
        f"SELECT v.*, p.name as profile_name, p.rate_limit, p.validity "
        f"FROM vouchers v LEFT JOIN profiles p ON v.profile_id = p.id "
        f"WHERE v.code IN ({format_strings}) AND v.reseller_id = %s",
        tuple(codes + [session['user_id']]), fetch=True
    ) or []
    
    return render_template('reseller/thermal_print.html', vouchers=vouchers)

@reseller_bp.route('/print_vouchers')
@reseller_required
def print_vouchers():
    codes_str = request.args.get('codes', '')
    if not codes_str:
        return redirect(url_for('reseller.history'))
        
    codes = codes_str.split(',')
    format_strings = ','.join(['%s'] * len(codes))
    vouchers = execute_query(
        f"SELECT v.*, p.name as profile_name, p.rate_limit, p.validity "
        f"FROM vouchers v LEFT JOIN profiles p ON v.profile_id = p.id "
        f"WHERE v.code IN ({format_strings}) AND v.reseller_id = %s",
        tuple(codes + [session['user_id']]), fetch=True
    ) or []
    
    return render_template('vouchers/print.html', vouchers=vouchers)

@reseller_bp.route('/history')
@reseller_required
def history():
    balance, discount_percent = get_reseller_data()
    
    vouchers = execute_query(
        "SELECT v.*, p.name as profile_name FROM vouchers v "
        "LEFT JOIN profiles p ON v.profile_id = p.id "
        "WHERE v.reseller_id=%s ORDER BY v.created_at DESC",
        (session['user_id'],), fetch=True
    ) or []
    
    return render_template(
        'reseller/history.html', 
        vouchers=vouchers,
        balance=balance, 
        discount_percent=discount_percent
    )
