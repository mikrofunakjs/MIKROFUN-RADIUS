from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from web.database import execute_query
from werkzeug.security import check_password_hash, generate_password_hash
import os
import datetime

client_bp = Blueprint('client', __name__)

@client_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('client_user'):
        return redirect(url_for('client.dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Fetch user by username only (password now hashed)
        user = execute_query(
            "SELECT * FROM customers WHERE username=%s",
            (username,), fetch_one=True
        )
        
        is_valid = False
        if user:
            stored_pw = user.get('password', '')
            
            # Werkzeug hashes contain ':' (e.g., scrypt:32768:8:1$salt$hash)
            if ':' in stored_pw:
                try:
                    is_valid = check_password_hash(stored_pw, password)
                except Exception:
                    is_valid = (stored_pw == password)
            else:
                # Plaintext (legacy)
                is_valid = (stored_pw == password)
                # Auto-upgrade to hash
                if is_valid:
                    try:
                        new_hash = generate_password_hash(password)
                        execute_query("UPDATE customers SET password=%s WHERE username=%s", (new_hash, username))
                    except Exception:
                        pass
        
        if is_valid:
            session['client_user'] = user
            return redirect(url_for('client.dashboard'))
        else:
            flash('Username atau Password salah!', 'error')
            
    return render_template('client/login.html')

@client_bp.route('/logout')
def logout():
    session.pop('client_user', None)
    return redirect(url_for('client.login'))

@client_bp.route('/')
def dashboard():
    try:
        user = session.get('client_user')
        if not user:
            return redirect(url_for('client.login'))
            
        # Refresh user data
        user_data = execute_query(
            "SELECT c.*, p.name as profile_name FROM customers c "
            "LEFT JOIN profiles p ON c.profile_id = p.id "
            "WHERE c.id=%s", 
            (user['id'],), fetch_one=True
        )
        if not user_data:
            return redirect(url_for('client.logout'))
            
        # Get Usage (From active_sessions if online)
        active = None
        try:
            active = execute_query("SELECT * FROM active_sessions WHERE username=%s", (user_data['username'],), fetch_one=True)
        except Exception as e:
            print(f"Active Session Query Error: {e}") # Log it
            pass
            
        # Get Total Usage (Accounting)
        usage = {'upload': 0, 'download': 0}
        try:
            usage_data = execute_query(
                "SELECT COALESCE(SUM(acctinputoctets),0) as upload, COALESCE(SUM(acctoutputoctets),0) as download "
                "FROM radacct WHERE username=%s", 
                (user_data['username'],), fetch_one=True
            )
            if usage_data:
                usage = usage_data
        except Exception as e:
             print(f"Usage Query Error: {e}")

        # Get Pending Bill / Payment History
        payments = []
        try:
            payments = execute_query("SELECT * FROM payments WHERE customer_id=%s ORDER BY created_at DESC LIMIT 5", (user['id'],), fetch=True) or []
        except Exception as e:
            print(f"Payments Query Error: {e}")
            pass

        return render_template('client/dashboard.html', user=user_data, active=active, payments=payments, usage=usage, today=datetime.date.today())
    except Exception as e:
        import traceback
        return f"<h3>Client Portal Error</h3><pre>{traceback.format_exc()}</pre>"

@client_bp.route('/pay', methods=['GET', 'POST'])
def pay():
    user = session.get('client_user')
    if not user: return redirect(url_for('client.login'))
    
    # Get Settings
    settings_rows = execute_query("SELECT * FROM settings", fetch=True) or []
    settings = {row['setting_key']: row['setting_value'] for row in settings_rows}
    
    active_gateway = settings.get('active_gateway', 'manual')

    if request.method == 'POST':
        payment_method = request.form.get('payment_method', 'manual')
        raw_amount = request.form.get('amount', '0')
        
        # Safe amount cleaning for all methods
        try:
            amount = int(float(raw_amount))
        except (ValueError, TypeError):
            flash('Nominal pembayaran tidak valid.', 'error')
            return redirect(url_for('client.pay'))
        
        # --- TRIPAY PAYMENT ---
        if payment_method == 'tripay':
            method_code = request.form.get('method_code')
            from web.tripay_helper import TripayHelper
            tripay = TripayHelper()
            
            # Create Transaction
            customer_data = {
                'id': user['id'],
                'first_name': user.get('name') or user['username'],
                'email': user.get('email') or f"{user['username']}@mikrofun.local",
                'phone': user.get('phone') or '08123456789'
            }
            order_items = [
                {'name': 'Internet Bill Payment', 'price': int(amount), 'quantity': 1}
            ]
            
            data, error = tripay.request_transaction(method_code, int(amount), customer_data, order_items)
            
            if error:
                flash(f'Gagal membuat transaksi Tripay: {error}', 'error')
                return redirect(url_for('client.pay'))
                
            # Save Pending Payment
            execute_query(
                "INSERT INTO payments (customer_id, amount, payment_channel, external_ref, checkout_url, status, created_at) "
                "VALUES (%s, %s, %s, %s, %s, 'pending', NOW())",
                (user['id'], amount, data['payment_method'], data['reference'], data['checkout_url'])
            )
            
            return redirect(data['checkout_url'])

        # --- MIDTRANS PAYMENT ---
        elif payment_method == 'midtrans':
            # Midtrans usually generates token via AJAX or separate endpoint, 
            # but here we might handle the "Finish" step or initial token request?
            # Actually for Snap, the token is generated on Page Load or AJAX. 
            # Let's assume this POST is NOT used for Midtrans initiation if we use Snap Popup.
            # But if we use Redirection mode, we do it here.
            pass
            
        # --- DUITKU PAYMENT ---
        elif payment_method == 'duitku':
            method_code = request.form.get('method_code')
            if not method_code:
                flash("Silakan pilih channel pembayaran Duitku.", "error")
                return redirect(url_for('client.pay'))
                
            from web.duitku_helper import DuitkuHelper
            duitku = DuitkuHelper()
            
            customer_data = {
                'id': user['id'],
                'first_name': user.get('name') or user['username'],
                'email': user.get('email') or f"{user['username']}@mikrofun.local",
                'phone': user.get('phone') or '08123456789'
            }
            order_items = [{'name': 'Internet Bill Payment', 'price': int(amount), 'quantity': 1}]
            
            # Using current dummy callback URL placeholders as routing may differ
            callback_url = f"{request.url_root.rstrip('/')}{url_for('api.callback_duitku')}"
            returnUrl = f"{request.url_root.rstrip('/')}{url_for('client.dashboard')}"
            
            data, error = duitku.request_transaction(method_code, int(amount), customer_data, order_items, callback_url, returnUrl)
            
            if error or not data:
                flash(f'Gagal transaksi Duitku: {error}', 'error')
                return redirect(url_for('client.pay'))
                
            execute_query(
                "INSERT INTO payments (customer_id, amount, payment_channel, external_ref, checkout_url, status, created_at) "
                "VALUES (%s, %s, %s, %s, %s, 'pending', NOW())",
                (user['id'], amount, data['payment_method'], data['merchant_order_id'], data['checkout_url'])
            )
            return redirect(data['checkout_url'])

        # --- MANUAL TRANSFER / MOOTA ---
        elif payment_method == 'moota':
            # Auto generate 3 digit unique code
            import random
            unique_code = random.randint(101, 999)
            unique_amount = float(amount) + unique_code
            
            # Save pending payment with unique amount
            ext_ref = f"MTA-{user['id']}-{int(datetime.datetime.now().timestamp())}"
            execute_query(
                "INSERT INTO payments (customer_id, amount, payment_channel, external_ref, status, created_at) "
                "VALUES (%s, %s, 'MOOTA', %s, 'pending', NOW())",
                (user['id'], unique_amount, ext_ref)
            )
            flash(f'Silakan transfer TEPAT sejumlah Rp {"{:,.0f}".format(unique_amount).replace(",", ".")} agar otomatis lunas.', 'success')
            return redirect(url_for('client.dashboard'))
            
        else:
            sender_bank = request.form.get('sender_bank')
            sender_name = request.form.get('sender_name')
            bank_account_id = request.form.get('bank_account_id')
            proof = request.files.get('proof_image')
            
            # Save Proof Image
            # Use secure_filename in production if available, else simple clean
            import os
            from flask import current_app
            from werkzeug.utils import secure_filename
            
            filename = secure_filename(f"proof_{user['username']}_{int(datetime.datetime.now().timestamp())}.jpg")
            upload_folder = current_app.config['UPLOAD_FOLDER']
            
            try:
                proof.save(os.path.join(upload_folder, filename))
            except Exception as e:
                print(f"Failed to save proof: {e}")
                flash('Gagal menyimpan file bukti pembayaran.', 'error')
                return redirect(url_for('client.pay'))
            
            execute_query(
                "INSERT INTO payments (customer_id, amount, sender_bank, sender_name, bank_account_id, payment_date, proof_image, status, payment_channel) "
                "VALUES (%s, %s, %s, %s, %s, NOW(), %s, 'pending', %s)",
                (user['id'], amount, sender_bank, sender_name, bank_account_id, filename, payment_method)
            )
            flash('Bukti pembayaran dikirim. Menunggu verifikasi admin.', 'success')
            return redirect(url_for('client.dashboard'))
        
    # Get Bank Accounts
    banks = execute_query("SELECT * FROM bank_accounts WHERE is_active=1", fetch=True) or []
    
    # Get Customer Bill (Profile Price)
    customer_info = execute_query(
        "SELECT c.id, p.price FROM customers c JOIN profiles p ON c.profile_id = p.id WHERE c.id = %s",
        (user['id'],), fetch_one=True
    )
    total_bill = customer_info['price'] if customer_info else 0
    
    # Get Payment History
    payments = execute_query("SELECT * FROM payments WHERE customer_id=%s ORDER BY created_at DESC LIMIT 20", (user['id'],), fetch=True) or []
    
    # Helper Data for Page
    tripay_channels = []
    
    if active_gateway in ['tripay', 'both']:
        from web.tripay_helper import TripayHelper
        tripay_channels = TripayHelper().get_payment_channels()
        
    return render_template(
        'client/pay.html', 
        banks=banks, 
        user=user, 
        total_bill=total_bill,
        today=datetime.date.today().strftime('%Y-%m-%d'),
        active_gateway=active_gateway,
        tripay_channels=tripay_channels,
        settings=settings
    )

@client_bp.route('/history')
def history():
    user = session.get('client_user')
    if not user: return redirect(url_for('client.login'))
    
    # Get Payment History
    payments = execute_query("SELECT * FROM payments WHERE customer_id=%s ORDER BY created_at DESC LIMIT 50", (user['id'],), fetch=True) or []
    return render_template('client/history.html', payments=payments)

@client_bp.route('/buy_voucher')
def buy_voucher():
    user = session.get('client_user')
    if not user: return redirect(url_for('client.login'))
    
    # Check Premium Status via license service (not DB settings key)
    from web.license_service import is_premium
    if not is_premium():
        flash("Fitur Beli Voucher via Portal membutuhkan Lisensi PRO MikroFun.", "error")
        return redirect(url_for('client.dashboard'))
    
    # Get Voucher Profiles
    profiles = execute_query("SELECT * FROM profiles WHERE type='voucher' AND price > 0 ORDER BY price ASC", fetch=True) or []
    
    # Get active gateway
    settings_rows = execute_query("SELECT * FROM settings", fetch=True) or []
    settings = {row['setting_key']: row['setting_value'] for row in settings_rows}
    active_gateway = settings.get('active_gateway', 'manual')
    
    tripay_channels = []
    duitku_channels = []
    
    if active_gateway in ['tripay', 'both']:
        from web.tripay_helper import TripayHelper
        tripay_channels = TripayHelper().get_payment_channels()
        
    if active_gateway in ['duitku', 'both']:
        from web.duitku_helper import DuitkuHelper
        # Use a reasonable amount for inquiry
        min_amount = 10000
        if profiles:
            min_amount = min([p['price'] for p in profiles])
        duitku_channels, _error = DuitkuHelper().get_payment_methods(int(min_amount))
        
    return render_template(
        'client/buy_voucher.html', 
        profiles=profiles, 
        active_gateway=active_gateway, 
        tripay_channels=tripay_channels, 
        duitku_channels=duitku_channels,
        settings=settings
    )

@client_bp.route('/buy_voucher/checkout', methods=['POST'])
def buy_voucher_checkout():
    user = session.get('client_user')
    if not user: return redirect(url_for('client.login'))
    
    # Check Premium via license service
    from web.license_service import is_premium
    if not is_premium():
        flash("Fitur Beli Voucher dinonaktifkan.", "error")
        return redirect(url_for('client.dashboard'))
    
    profile_id = request.form.get('profile_id')
    payment_method = request.form.get('payment_method') # tripay, midtrans, manual, duitku
    
    if not profile_id:
        flash("Pilih paket voucher terlebih dahulu.", "error")
        return redirect(url_for('client.buy_voucher'))
        
    profile = execute_query("SELECT * FROM profiles WHERE id=%s", (profile_id,), fetch_one=True)
    if not profile or profile['price'] <= 0:
        flash("Paket voucher tidak valid.", "error")
        return redirect(url_for('client.buy_voucher'))
        
    amount = profile['price']
    
    # --- TRIPAY PAYMENT ---
    if payment_method == 'tripay':
        method_code = request.form.get('method_code')
        if not method_code:
            flash("Silakan pilih channel pembayaran Tripay.", "error")
            return redirect(url_for('client.buy_voucher'))
            
        from web.tripay_helper import TripayHelper
        tripay = TripayHelper()
        
        # Determine tracking URL
        import time
        merchant_ref = f"VC-{user['id']}-{int(time.time())}"
        
        host = request.headers.get('Host', request.host)
        proto = request.headers.get('X-Forwarded-Proto', 'http')
        tracking_url = f"{proto}://{host}/api/public/track_voucher?ref={merchant_ref}"
        
        customer_data = {
            'id': user['id'],
            'first_name': user.get('name') or user['username'],
            'email': user.get('email') or f"{user['username']}@mikrofun.local",
            'phone': user.get('phone') or '08123456789'
        }
        order_items = [
            {'name': f"Voucher: {profile['name']}", 'price': int(amount), 'quantity': 1}
        ]
        
        data, error = tripay.request_transaction(method_code, int(amount), customer_data, order_items, return_url=tracking_url)
        
        if error:
            flash(f'Gagal transaksi Tripay: {error}', 'error')
            return redirect(url_for('client.buy_voucher'))
            
        execute_query(
            "INSERT INTO payments (customer_id, amount, payment_channel, external_ref, checkout_url, status, created_at, payment_type, profile_id) "
            "VALUES (%s, %s, %s, %s, %s, 'pending', NOW(), 'voucher', %s)",
            (user['id'], amount, data['payment_method'], data['reference'], data['checkout_url'], profile_id)
        )
        return redirect(data['checkout_url'])
        
    # --- MIDTRANS PAYMENT ---
    elif payment_method == 'midtrans':
        # Handled via AJAX usually, unless redirect mode is used. 
        flash('Silakan gunakan tombol Bayar Instant Midtrans.', 'info')
        return redirect(url_for('client.buy_voucher'))
        
    # --- DUITKU PAYMENT ---
    elif payment_method == 'duitku':
        method_code = request.form.get('method_code')
        if not method_code:
            flash("Silakan pilih channel pembayaran Duitku.", "error")
            return redirect(url_for('client.buy_voucher'))
            
        from web.duitku_helper import DuitkuHelper
        duitku = DuitkuHelper()
        
        import time
        merchant_ref = f"VC-{user['id']}-{int(time.time())}"
        
        host = request.headers.get('Host', request.host)
        proto = request.headers.get('X-Forwarded-Proto', 'http')
        callback_url = f"{proto}://{host}/api/callback/duitku"
        tracking_url = f"{proto}://{host}/api/public/track_voucher?ref={merchant_ref}"
        
        customer_data = {
            'id': user['id'],
            'first_name': user.get('name') or user['username'],
            'email': user.get('email') or f"{user['username']}@mikrofun.local",
            'phone': user.get('phone') or '08123456789'
        }
        order_items = [{'name': f"Voucher: {profile['name']}", 'price': int(amount), 'quantity': 1}]
        
        data, error = duitku.request_transaction(method_code, int(amount), customer_data, order_items, callback_url, tracking_url, merchant_ref)
        
        if error or not data:
            flash(f'Gagal transaksi Duitku: {error}', 'error')
            return redirect(url_for('client.buy_voucher'))
            
        execute_query(
            "INSERT INTO payments (customer_id, amount, payment_channel, external_ref, checkout_url, status, created_at, payment_type, profile_id) "
            "VALUES (%s, %s, %s, %s, %s, 'pending', NOW(), 'voucher', %s)",
            (user['id'], amount, data['payment_method'], data['merchant_order_id'], data['checkout_url'], profile_id)
        )
        return redirect(data['checkout_url'])
        
    # --- MOOTA PAYMENT ---
    elif payment_method == 'moota':
        import random
        unique_code = random.randint(101, 999)
        unique_amount = float(amount) + unique_code
        
        ext_ref = f"MTA-VC-{user['id']}-{int(datetime.datetime.now().timestamp())}"
        execute_query(
            "INSERT INTO payments (customer_id, amount, payment_channel, external_ref, status, created_at, payment_type, profile_id) "
            "VALUES (%s, %s, 'MOOTA', %s, 'pending', NOW(), 'voucher', %s)",
            (user['id'], unique_amount, ext_ref, profile_id)
        )
        flash(f'Silakan transfer TEPAT sejumlah Rp {"{:,.0f}".format(unique_amount).replace(",", ".")} untuk Voucher {profile["name"]} agar otomatis lunas.', 'success')
        return redirect(url_for('client.dashboard'))

    # --- MANUAL TRANSFER ---
    else:
        sender_bank = request.form.get('sender_bank')
        sender_name = request.form.get('sender_name')
        bank_account_id = request.form.get('bank_account_id')
        proof = request.files.get('proof_image')
        
        if not proof or not proof.filename:
            flash("Harap unggah bukti transfer.", "error")
            return redirect(url_for('client.buy_voucher'))
            
        import os
        from flask import current_app
        import datetime
        from werkzeug.utils import secure_filename
        
        filename = secure_filename(f"voucher_{user['username']}_{int(datetime.datetime.now().timestamp())}.jpg")
        upload_folder = current_app.config['UPLOAD_FOLDER']
        
        try:
            proof.save(os.path.join(upload_folder, filename))
        except Exception as e:
            flash('Gagal menyimpan file bukti.', 'error')
            return redirect(url_for('client.buy_voucher'))
            
        execute_query(
            "INSERT INTO payments (customer_id, amount, sender_bank, sender_name, bank_account_id, payment_date, proof_image, status, payment_type, profile_id) "
            "VALUES (%s, %s, %s, %s, %s, NOW(), %s, 'pending', 'voucher', %s)",
            (user['id'], amount, sender_bank, sender_name, bank_account_id, filename, profile_id)
        )
        flash('Bukti pembelian terkirim. Menunggu verifikasi admin.', 'success')
        return redirect(url_for('client.history'))

@client_bp.route('/invoice/<int:payment_id>')
def invoice(payment_id):
    user = session.get('client_user')
    if not user: return redirect(url_for('client.login'))
    
    # Get Payment & Verify Ownership
    payment = execute_query("SELECT * FROM payments WHERE id=%s AND customer_id=%s", (payment_id, user['id']), fetch_one=True)
    if not payment:
        flash('Invoice tidak ditemukan.', 'error')
        return redirect(url_for('client.pay'))
        
    # Get Company Settings
    company = {}
    settings_rows = execute_query("SELECT * FROM settings WHERE setting_key LIKE 'company_%'", fetch=True) or []
    for row in settings_rows:
        key = row['setting_key'].replace('company_', '')
        company[key] = row['setting_value']
        
    return render_template('client/invoice.html', payment=payment, user=user, company=company)

# --- Helpdesk Routes ---

@client_bp.route('/tickets')
def tickets():
    user = session.get('client_user')
    if not user: return redirect(url_for('client.login'))
    
    tickets = execute_query(
        "SELECT * FROM tickets WHERE customer_id=%s ORDER BY updated_at DESC", 
        (user['id'],), fetch=True
    ) or []
    
    return render_template('client/tickets/index.html', tickets=tickets)

@client_bp.route('/tickets/create', methods=['GET', 'POST'])
def ticket_create():
    user = session.get('client_user')
    if not user: return redirect(url_for('client.login'))
    
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()[:200]
        category = request.form.get('category', 'General').strip()[:64]
        message = request.form.get('message', '').strip()[:5000]

        if not subject or not message:
            flash('Subject dan pesan wajib diisi.', 'error')
            return render_template('client/tickets/create.html')

        ticket_id = execute_query(
            "INSERT INTO tickets (customer_id, subject, category, status, priority) VALUES (%s, %s, %s, 'open', 'medium')",
            (user['id'], subject, category)
        )

        if ticket_id:
            execute_query(
                "INSERT INTO ticket_replies (ticket_id, sender_type, sender_id, message) VALUES (%s, 'client', %s, %s)",
                (ticket_id, user['id'], message)
            )
            flash('Tiket berhasil dibuat.', 'success')
        else:
            flash('Gagal membuat tiket. Silakan coba lagi.', 'error')

        return redirect(url_for('client.tickets'))
        
    return render_template('client/tickets/create.html')

@client_bp.route('/tickets/<int:id>', methods=['GET', 'POST'])
def ticket_view(id):
    user = session.get('client_user')
    if not user: return redirect(url_for('client.login'))
    
    # Verify ownership
    ticket = execute_query("SELECT * FROM tickets WHERE id=%s AND customer_id=%s", (id, user['id']), fetch_one=True)
    if not ticket:
        flash('Tiket tidak ditemukan.', 'error')
        return redirect(url_for('client.tickets'))
        
    if request.method == 'POST':
        message = request.form.get('message')
        if message:
            execute_query(
                "INSERT INTO ticket_replies (ticket_id, sender_type, sender_id, message) VALUES (%s, 'client', %s, %s)",
                (id, user['id'], message)
            )
            # Update Ticket Timestamp & Status (if it was answered, maybe set back to open? Optional)
            execute_query("UPDATE tickets SET status='open', updated_at=NOW() WHERE id=%s", (id,))
            flash('Balasan terkirim.', 'success')
            return redirect(url_for('client.ticket_view', id=id))

    replies = execute_query(
        "SELECT * FROM ticket_replies WHERE ticket_id=%s ORDER BY created_at ASC", 
        (id,), fetch=True
    ) or []
    
    return render_template('client/tickets/view.html', ticket=ticket, replies=replies, user=user)

@client_bp.route('/pay/midtrans-token', methods=['POST'])
def midtrans_token():
    user = session.get('client_user')
    if not user: return {'error': 'Unauthorized'}, 401
    
    amount = request.json.get('amount')
    if not amount: return {'error': 'Invalid amount'}, 400
    
    # Safe conversion: handle strings like '500000.00'
    try:
        amount_int = int(float(amount))
    except (ValueError, TypeError):
        return {'error': 'Invalid amount format'}, 400
    
    # Generate Order ID
    import time
    order_id = f"M-{user['id']}-{int(time.time())}"
    
    # Call Midtrans Helper
    from web.midtrans_helper import MidtransHelper
    helper = MidtransHelper()
    
    customer_data = {
        'first_name': user.get('name') or user['username'],
        'email': user.get('email') or f"{user['username']}@mikrofun.local",
        'phone': user.get('phone') or '08123456789'
    }
    
    token_data, error = helper.get_snap_token(order_id, amount_int, customer_data)
    
    if token_data and 'token' in token_data:
        # Save Pending Payment (Waiting for pay)
        execute_query(
            "INSERT INTO payments (customer_id, amount, payment_channel, external_ref, status, created_at) "
            "VALUES (%s, %s, 'MIDTRANS', %s, 'pending', NOW())",
            (user['id'], amount_int, order_id)
        )
        return {'token': token_data.get('token'), 'redirect_url': token_data.get('redirect_url')}
        
    return {'error': error or 'Failed to generate token'}, 500

@client_bp.route('/buy_voucher/midtrans-token', methods=['POST'])
def buy_voucher_midtrans_token():
    user = session.get('client_user')
    if not user: return {'error': 'Unauthorized'}, 401
    
    profile_id = request.json.get('profile_id')
    if not profile_id: return {'error': 'Profile ID is required'}, 400
    
    profile = execute_query("SELECT * FROM profiles WHERE id=%s", (profile_id,), fetch_one=True)
    if not profile or profile['price'] <= 0: return {'error': 'Invalid profile'}, 400
    
    from web.midtrans_helper import MidtransHelper
    helper = MidtransHelper()
    
    import time
    order_id = f"V-{user['id']}-{int(time.time())}"
    
    # Safe conversion: handle strings like '500000.00'
    try:
        amount_int = int(float(profile['price']))
    except (ValueError, TypeError):
        return {'error': 'Invalid profile price'}, 400
    
    customer_data = {
        'first_name': user.get('name') or user['username'],
        'email': user.get('email') or f"{user['username']}@mikrofun.local",
        'phone': user.get('phone') or '08123456789'
    }
    
    token_data, error = helper.get_snap_token(order_id, amount_int, customer_data)
    
    if token_data and 'token' in token_data:
        execute_query(
            "INSERT INTO payments (customer_id, amount, payment_channel, external_ref, status, created_at, payment_type, profile_id) "
            "VALUES (%s, %s, 'MIDTRANS', %s, 'pending', NOW(), 'voucher', %s)",
            (user['id'], amount_int, order_id, profile_id)
        )
        return {'token': token_data.get('token'), 'redirect_url': token_data.get('redirect_url')}
        
    return {'error': error or 'Failed to generate token'}, 500
