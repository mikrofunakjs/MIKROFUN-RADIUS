from flask import Blueprint, request, jsonify
from web.database import execute_query
import json
import datetime
from dateutil.relativedelta import relativedelta
import secrets
import string

api_bp = Blueprint('api', __name__)

@api_bp.route('/callback/tripay', methods=['POST'])
def callback_tripay():
    # 1. Get Signature & Data
    signature = request.headers.get('X-Callback-Signature')
    json_data = request.data.decode('utf-8') # Raw Body
    data = request.json
    
    # 2. Verify Signature
    from web.tripay_helper import TripayHelper
    helper = TripayHelper()
    
    if not helper.verify_callback_signature(json_data, signature):
        return jsonify({'success': False, 'message': 'Invalid Signature'}), 400
        
    # 3. Process Status
    # Event types: payment_status (paid, expired, failed)
    event = request.headers.get('X-Callback-Event')
    
    if event == 'payment_status':
        status = data.get('status') # PAID, EXPIRED, FAILED
        merchant_ref = data.get('merchant_ref')
        tripay_ref = data.get('reference')
        
        if status == 'PAID':
            payment = execute_query("SELECT external_ref FROM payments WHERE external_ref=%s AND status='pending' LIMIT 1", (merchant_ref,), fetch_one=True)
            if payment:
                process_successful_payment(payment['external_ref'], 'TRIPAY')
        elif status in ['EXPIRED', 'FAILED']:
            payment = execute_query("SELECT external_ref FROM payments WHERE external_ref=%s AND status='pending' LIMIT 1", (merchant_ref,), fetch_one=True)
            if payment:
                update_payment_status(payment['external_ref'], 'failed')
            
    return jsonify({'success': True})

@api_bp.route('/callback/midtrans', methods=['POST'])
def callback_midtrans():
    data = request.json
    
    order_id = data.get('order_id')
    status_code = data.get('status_code')
    gross_amount = data.get('gross_amount')
    signature_key = data.get('signature_key')
    transaction_status = data.get('transaction_status')
    
    # 1. Verify Signature
    from web.midtrans_helper import MidtransHelper
    helper = MidtransHelper()

    if not helper.verify_signature(order_id, status_code, gross_amount, signature_key):
        return jsonify({'success': False, 'message': 'Invalid Signature'}), 400

    # 2. Process Status
    if transaction_status in ['capture', 'settlement']:
        process_successful_payment(order_id, 'MIDTRANS')
    elif transaction_status in ['deny', 'cancel', 'expire']:
        update_payment_status(order_id, 'failed')
        
    return jsonify({'success': True})

@api_bp.route('/callback/moota', methods=['POST'])
def callback_moota():
    signature = request.headers.get('Signature')
    if not signature:
        return jsonify({'success': False, 'message': 'Missing Signature header'}), 400
        
    raw_data = request.data
    
    # 1. Verify Signature
    from web.moota_helper import MootaHelper
    helper = MootaHelper()
    
    if not helper.verify_webhook_signature(signature, raw_data):
        return jsonify({'success': False, 'message': 'Invalid Signature'}), 400
        
    # 2. Process Data
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': 'Empty Payload'}), 400
            
        # Moota often wraps mutations in a list inside 'data' or sends list directly depending on version/config
        # Standard Moota V2 Webhook structure is usually an array of mutations
        mutations = data if isinstance(data, list) else data.get('data', [])
        
        processed_count = 0
        for mutation in mutations:
            # We only care about CREDIT (uang masuk)
            if str(mutation.get('type', '')).upper() != 'CR':
                continue
                
            amount = float(mutation.get('amount', 0))
            if amount <= 0:
                continue
                
            # Find a pending payment with this exact amount
            # Since amount includes a 3-digit unique code, it's highly likely to be unique
            # If multiple exist, take the oldest pending one
            pending_payment = execute_query(
                "SELECT id, external_ref FROM payments WHERE amount=%s AND payment_channel='MOOTA' AND status='pending' ORDER BY created_at ASC LIMIT 1",
                (amount,), fetch_one=True
            )
            
            if pending_payment:
                # Mark as approved utilizing the same function used by Tripay/Midtrans
                process_successful_payment(pending_payment['external_ref'], 'MOOTA')
                processed_count += 1
                
        return jsonify({'success': True, 'processed': processed_count})
        
    except Exception as e:
        print(f"Moota Webhook Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@api_bp.route('/callback/duitku', methods=['POST'])
def callback_duitku():
    try:
        data = request.form.to_dict()
        if not data:
            data = request.json
            
        if not data:
            return jsonify({'success': False, 'message': 'Empty Payload'}), 400
            
        from web.duitku_helper import DuitkuHelper
        helper = DuitkuHelper()
        
        # Verify Signature
        if not helper.verify_callback(data):
            return jsonify({'success': False, 'message': 'Invalid Signature'}), 400
            
        result_code = data.get('resultCode')
        merchant_order_id = data.get('merchantOrderId')
        
        if result_code == '00': # Success
            process_successful_payment(merchant_order_id, 'DUITKU')
        elif result_code == '01': # Failed
            update_payment_status(merchant_order_id, 'failed')
            
        return jsonify({'success': True}), 200
        
    except Exception as e:
        print(f"Duitku Webhook Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@api_bp.route('/duitku_methods', methods=['GET'])
def duitku_methods():
    try:
        amount = request.args.get('amount', type=int)
        if not amount or amount < 10000:
            return jsonify({'success': False, 'message': 'Invalid amount, minimum 10000'}), 400
            
        from web.duitku_helper import DuitkuHelper
        helper = DuitkuHelper()
        methods, error = helper.get_payment_methods(amount)
        
        return jsonify({'success': True if methods else False, 'methods': methods, 'error': error})
    except Exception as e:
        import traceback
        print(f"DEBUG Duitku Exception: {traceback.format_exc()}")
        return jsonify({'success': False, 'message': f"Internal Server Error: {str(e)}"}), 500

def process_successful_payment(reference, gateway_name):
    """
    Common logic to approve payment and activate user.
    Uses atomic row-count check to prevent double-processing.
    reference: external_ref in payments table
    """
    rows = execute_query(
        "UPDATE payments SET status='processing' WHERE external_ref=%s AND status='pending'",
        (reference,)
    )
    if not rows or rows == 0:
        print(f"Payment already processed or not found: {reference}")
        return

    payment = execute_query(
        "SELECT * FROM payments WHERE external_ref=%s",
        (reference,), fetch_one=True
    )
    if not payment:
        print(f"Payment not found: {reference}")
        return
        
    # 2. Process business logic FIRST (before marking payment approved)
    customer_name = "Guest (Public Voucher)"
    voucher_code = None
    try:
        if payment.get('payment_type') == 'voucher':
            voucher_code = generate_voucher_for_payment(payment)
        elif payment.get('payment_type') == 'reseller_topup':
            if payment.get('reseller_id'):
                activate_reseller_topup(payment['reseller_id'], payment['amount'], reference)
                res = execute_query("SELECT username FROM users WHERE id=%s", (payment['reseller_id'],), fetch_one=True)
                if res: customer_name = f"Reseller: {res['username']}"
        else:
            # Bill payment: Activate Customer
            if payment.get('customer_id'):
                activate_customer(payment['customer_id'], payment['amount'])
                cust = execute_query("SELECT name FROM customers WHERE id=%s", (payment['customer_id'],), fetch_one=True)
                if cust: customer_name = cust.get('name', 'Unknown')
    except Exception as e:
        print(f"Payment processing failed for {reference}: {e}")
        update_payment_status(reference, 'failed')
        return

    # 3. NOW mark payment as approved (only after business logic succeeds)
    execute_query(
        "UPDATE payments SET status='approved', payment_date=NOW(), voucher_code=%s WHERE id=%s",
        (voucher_code, payment['id'])
    )

    # ── FINANCE LEDGER: catat pembayaran gateway online ──────────────────────
    if payment.get('payment_type') != 'reseller_topup':
        try:
            from web.finance_helper import record_client_payment
            _pay_enriched = dict(payment)
            _pay_enriched['payment_channel'] = gateway_name
            record_client_payment(_pay_enriched, customer_name)
        except Exception as _fe:
            print(f"[finance] warn webhook: {_fe}")
    # ─────────────────────────────────────────────────────────────────────────
            
    # 4. Notify Admin via Telegram
    try:
        from web.telegram_helper import send_telegram_message
        amount_fmt = '{:,.0f}'.format(payment.get('amount', 0)).replace(',', '.')
        msg = (f"💰 *PEMBAYARAN MASUK*\n\n"
               f"Layanan: `{gateway_name}`\n"
               f"Pelanggan: {customer_name}\n"
               f"Tipe: {payment.get('payment_type', 'bill').upper()}\n"
               f"Nominal: *Rp {amount_fmt}*\n"
               f"Status: ✅ LUNAS\n"
               f"Ref: `{reference}`")
        send_telegram_message(msg)
    except Exception as e:
        print(f"Telegram Notification Error: {e}")

def generate_voucher_for_payment(payment):
    """
    Auto-generates a hotspot voucher when a payment is marked PAID.
    Returns the generated voucher code, or None on failure.
    """
    profile_id = payment.get('profile_id')
    if not profile_id:
        return None
    
    profile = execute_query("SELECT * FROM profiles WHERE id=%s", (profile_id,), fetch_one=True)
    if not profile:
        return None
    
    import string as _string
    code = ''.join(secrets.choice(_string.ascii_uppercase + _string.digits) for _ in range(8))
    
    execute_query(
        "INSERT INTO radcheck (username, attribute, op, value) VALUES (%s, 'Cleartext-Password', ':=', %s)",
        (code, code)
    )
    
    execute_query(
        "INSERT INTO radusergroup (username, groupname, priority) VALUES (%s, %s, 1)",
        (code, profile['name'])
    )
    
    validity = int(profile.get('validity', 24))
    unit = profile.get('validity_unit', 'hours')
    
    duration_hours = validity
    if unit == 'days':
        duration_hours = validity * 24
    elif unit == 'months':
        duration_hours = validity * 720

    execute_query(
        "INSERT INTO vouchers (code, profile_id, duration_hours) VALUES (%s, %s, %s)",
        (code, profile_id, duration_hours)
    )
    
    # Optional WA notification
    try:
        from web.wa_helper import send_wa_notification
        phone_target = payment.get('guest_phone')
        
        if not phone_target and payment.get('customer_id'):
            customer = execute_query("SELECT phone FROM customers WHERE id=%s", (payment['customer_id'],), fetch_one=True)
            if customer:
                phone_target = customer.get('phone')
                
        if phone_target:
            send_wa_notification(phone_target, 'voucher_purchase', code=code, profile_name=profile['name'])
        else:
            print(f"WA Notification skipped: no phone number for payment {payment.get('id')}")
    except Exception as e:
        print(f"WA Error Voucher: {e}")

    return code

def update_payment_status(reference, status):
    execute_query(
        "UPDATE payments SET status=%s WHERE external_ref=%s AND status IN ('pending', 'processing')",
        (status, reference)
    )

def activate_customer(customer_id, amount_paid=None):
    # 1. Get Customer
    customer = execute_query("SELECT * FROM customers WHERE id=%s", (customer_id,), fetch_one=True)
    if not customer:
        return

    # 2. Calculate New Due Date
    import datetime
    
    today = datetime.date.today()
    
    if customer['due_date'] and customer['due_date'] >= today:
        new_due_date = customer['due_date'] + relativedelta(months=1)
    else:
        new_due_date = today + relativedelta(months=1)
        
    # 3. Update Customer
    execute_query(
        "UPDATE customers SET status='active', due_date=%s WHERE id=%s",
        (new_due_date, customer_id)
    )
    
    # 4. Trigger Notification (WA) — format due_date to Indonesian style
    try:
        from web.wa_helper import send_wa_notification
        due_str = new_due_date.strftime('%d/%m/%Y') if new_due_date else ''
        send_wa_notification(customer.get('phone', ''), 'bill_payment', due_date=due_str)
    except Exception as e:
        print(f"WA Error: {e}")
        
    # 5. Re-Apply Advanced PPPoE/Hotspot parameters (CoA)
    try:
        from web.radius_helper import send_disconnect_packet
        from web.config import RADIUS_SECRET
        if customer.get('router_id'):
            router = execute_query("SELECT ip_address FROM routers WHERE id=%s", (customer['router_id'],), fetch_one=True)
            if router and router.get('ip_address'):
                secret = RADIUS_SECRET.encode() if isinstance(RADIUS_SECRET, str) else RADIUS_SECRET
                send_disconnect_packet(router['ip_address'], secret, customer['username'])
    except Exception as e:
        print(f"CoA Error for customer {customer.get('username', customer_id)}: {e}")

def activate_reseller_topup(reseller_id, amount, reference):
    """Update reseller balance and record transaction"""
    reseller = execute_query("SELECT balance FROM users WHERE id=%s AND role='reseller'", (reseller_id,), fetch_one=True)
    if not reseller: return
    
    balance_before = float(reseller['balance'])
    balance_after = balance_before + float(amount)
    
    execute_query("UPDATE users SET balance = %s WHERE id = %s", (balance_after, reseller_id))
    execute_query(
        "INSERT INTO reseller_transactions (reseller_id, type, amount, description, balance_before, balance_after) VALUES (%s, 'topup', %s, %s, %s, %s)",
        (reseller_id, amount, f"Top-Up via Payment Gateway (Ref: {reference})", balance_before, balance_after)
    )
    
    # Ledger record
    try:
        from web.finance_helper import record_mitra_deposit
        r = execute_query("SELECT username FROM users WHERE id=%s", (reseller_id,), fetch_one=True)
        record_mitra_deposit(reseller_id, r['username'] if r else f'ID-{reseller_id}', amount, f"Gateway-{reference}")
    except Exception as _fe:
        print(f"[finance] warn: {_fe}")

@api_bp.route('/callback/xendit', methods=['POST'])
def callback_xendit():
    """Xendit webhook callback for payment status"""
    try:
        callback_token = request.headers.get('x-callback-token', '')
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': 'Empty payload'}), 400

        from web.xendit_helper import XenditHelper
        helper = XenditHelper()

        # Verify webhook token
        if not helper.verify_callback(callback_token):
            return jsonify({'success': False, 'message': 'Invalid callback token'}), 403

        status = data.get('status', '')
        external_id = data.get('external_id', '')
        amount = data.get('amount', 0)

        if status == 'PAID':
            payment = execute_query(
                "SELECT external_ref FROM payments WHERE external_ref=%s AND status='pending' LIMIT 1",
                (external_id,), fetch_one=True
            )
            if payment:
                process_successful_payment(payment['external_ref'], 'XENDIT')
        elif status == 'EXPIRED':
            payment = execute_query(
                "SELECT external_ref FROM payments WHERE external_ref=%s AND status='pending' LIMIT 1",
                (external_id,), fetch_one=True
            )
            if payment:
                update_payment_status(payment['external_ref'], 'failed')

        return jsonify({'success': True})
    except Exception as e:
        print(f"Xendit Webhook Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@api_bp.route('/public/buy_voucher', methods=['POST'])
def public_buy_voucher():
    """Endpoint for landing page to initiate a voucher purchase via Tripay"""
    from flask import flash, redirect
    
    profile_id = request.form.get('profile_id')
    payment_method = request.form.get('payment_method')
    method_code = request.form.get('method_code')
    guest_email = request.form.get('guest_email')
    guest_phone = request.form.get('guest_phone')
    
    if not profile_id or not payment_method or not guest_email or not guest_phone:
        flash("Mohon lengkapi semua data pembelian (Paket, Email, dan No WA).", "error")
        return redirect('/landing-page')
        
    profile = execute_query("SELECT * FROM profiles WHERE id=%s", (profile_id,), fetch_one=True)
    if not profile or profile['price'] <= 0:
        flash("Paket voucher tidak valid.", "error")
        return redirect('/landing-page')
        
    amount = profile['price']
    
    # TRIPAY
    if payment_method == 'tripay':
        if not method_code:
            flash("Silakan pilih saluran Tripay.", "error")
            return redirect('/landing-page')
            
        from web.tripay_helper import TripayHelper
        tripay = TripayHelper()
        
        customer_data = {
            'first_name': 'Guest',
            'last_name': 'Buyer',
            'email': guest_email,
            'phone': guest_phone
        }
        order_items = [
            {'name': f"Voucher: {profile['name']}", 'price': int(amount), 'quantity': 1}
        ]
        
        # Determine tracking URL
        # Generate merchant_ref ahead of time to build URL
        import time
        merchant_ref = f"VPUB-{int(time.time())}-{int(amount)}"
        
        # Robust return URL: Use the host from request headers if behind proxy
        host = request.headers.get('Host', request.host)
        proto = request.headers.get('X-Forwarded-Proto', 'http')
        tracking_url = f"{proto}://{host}/api/public/track_voucher?ref={merchant_ref}"
        
        data, error = tripay.request_transaction(method_code, int(amount), customer_data, order_items, return_url=tracking_url, merchant_ref=merchant_ref)
        
        if error:
            flash(f'Gagal transaksi Tripay: {error}', 'error')
            return redirect('/landing-page')
            
        execute_query(
            "INSERT INTO payments (amount, payment_channel, external_ref, checkout_url, status, created_at, payment_type, profile_id, guest_email, guest_phone) "
            "VALUES (%s, %s, %s, %s, 'pending', NOW(), 'voucher', %s, %s, %s)",
            (amount, data['payment_method'], merchant_ref, data['checkout_url'], profile_id, guest_email, guest_phone)
        )
        return redirect(data['checkout_url'])
        
    # DUITKU
    if payment_method == 'duitku':
        method_code = request.form.get('method_code')
        if not method_code:
            flash("Silakan pilih saluran Duitku.", "error")
            return redirect('/landing-page')
            
        from web.duitku_helper import DuitkuHelper
        duitku = DuitkuHelper()
        
        import time
        customer_data = {
            'id': f"G-{int(time.time())}",
            'first_name': 'Guest',
            'email': guest_email,
            'phone': guest_phone
        }
        order_items = [
            {'name': f"Voucher: {profile['name']}", 'price': int(amount), 'quantity': 1}
        ]
        
        merchant_ref = f"VPUB-{int(time.time())}-{int(amount)}"
        
        host = request.headers.get('Host', request.host)
        proto = request.headers.get('X-Forwarded-Proto', 'http')
        callback_url = f"{proto}://{host}/api/callback/duitku"
        tracking_url = f"{proto}://{host}/api/public/track_voucher?ref={merchant_ref}"
        
        data, error = duitku.request_transaction(method_code, int(amount), customer_data, order_items, callback_url, tracking_url, merchant_ref)
        
        if error or not data:
            flash(f'Gagal transaksi Duitku: {error}', 'error')
            return redirect('/landing-page')
        execute_query(
            "INSERT INTO payments (amount, payment_channel, external_ref, checkout_url, status, created_at, payment_type, profile_id, guest_email, guest_phone) "
            "VALUES (%s, %s, %s, %s, 'pending', NOW(), 'voucher', %s, %s, %s)",
            (amount, data['payment_method'], data['merchant_order_id'], data['checkout_url'], profile_id, guest_email, guest_phone)
        )
        return redirect(data['checkout_url'])
    
    # XENDIT
    if payment_method == 'xendit':
        from web.xendit_helper import XenditHelper
        xendit = XenditHelper()

        import time
        customer_data = {
            'first_name': 'Guest',
            'email': guest_email,
            'phone': guest_phone
        }
        order_items = [
            {'name': f"Voucher: {profile['name']}", 'price': int(amount), 'quantity': 1}
        ]

        merchant_ref = f"VPUB-{int(time.time())}-{int(amount)}"
        host = request.headers.get('Host', request.host)
        proto = request.headers.get('X-Forwarded-Proto', 'http')
        tracking_url = f"{proto}://{host}/api/public/track_voucher?ref={merchant_ref}"

        data, error = xendit.request_transaction(
            int(amount), customer_data, order_items,
            return_url=tracking_url, merchant_ref=merchant_ref
        )

        if error or not data:
            flash(f'Gagal transaksi Xendit: {error}', 'error')
            return redirect('/landing-page')

        execute_query(
            "INSERT INTO payments (amount, payment_channel, external_ref, checkout_url, status, created_at, payment_type, profile_id, guest_email, guest_phone) "
            "VALUES (%s, %s, %s, %s, 'pending', NOW(), 'voucher', %s, %s, %s)",
            (amount, data['payment_method'], data['merchant_order_id'], data['checkout_url'], profile_id, guest_email, guest_phone)
        )
        return redirect(data['checkout_url'])
    
    # MIDTRANS handled via AJAX usually
    flash('Metode pembayaran tidak didukung via Form. Gunakan Snap.', 'error')
    return redirect('/landing-page')

@api_bp.route('/public/buy_voucher_midtrans', methods=['POST'])
def public_buy_voucher_midtrans():
    """AJAX Endpoint for Midtrans Snap Token on Landing Page"""
    data = request.json
    profile_id = data.get('profile_id')
    guest_email = data.get('guest_email')
    guest_phone = data.get('guest_phone')
    
    if not profile_id or not guest_email or not guest_phone:
        return {'error': 'Mohon lengkapi Email dan No WA'}, 400
        
    profile = execute_query("SELECT * FROM profiles WHERE id=%s", (profile_id,), fetch_one=True)
    if not profile or profile['price'] <= 0:
        return {'error': 'Profile tidak valid'}, 400
        
    from web.midtrans_helper import MidtransHelper
    helper = MidtransHelper()
    
    import time
    order_id = f"VPUB-{int(time.time())}"
    amount = profile['price']
    
    customer_data = {
        'first_name': 'Guest',
        'email': guest_email,
        'phone': guest_phone
    }
    
    token_data, error = helper.get_snap_token(order_id, int(amount), customer_data)
    
    if token_data and 'token' in token_data:
        execute_query(
            "INSERT INTO payments (amount, payment_channel, external_ref, status, created_at, payment_type, profile_id, guest_email, guest_phone) "
            "VALUES (%s, 'MIDTRANS', %s, 'pending', NOW(), 'voucher', %s, %s, %s)",
            (amount, order_id, profile_id, guest_email, guest_phone)
        )
        tracking_url = f"/api/public/track_voucher?ref={order_id}"
        return {'token': token_data.get('token'), 'order_id': order_id, 'redirect_url': tracking_url}
        
    return {'error': error or 'Failed to generate token'}, 500

@api_bp.route('/public/track_voucher', methods=['GET'])
def public_track_voucher():
    """Endpoint for landing page to check transaction status"""
    # Tripay appends merchant_ref & reference to return_url
    # Duitku appends merchantOrderId
    ref = request.args.get('ref') or request.args.get('merchant_ref') or request.args.get('reference') or request.args.get('merchantOrderId')
    
    if not ref:
        return "Reference invalid (No ref/merchant_ref provided)", 400
        
    # Attempt to find by external_ref (which we used for merchant_ref or gateway_ref)
    payment = execute_query("SELECT * FROM payments WHERE external_ref=%s", (ref,), fetch_one=True)
    
    if not payment:
        # Debugging: show what we searched for
        return f"Transaksi tidak ditemukan untuk referensi: {ref}", 404
        
    from flask import render_template
    return render_template('public/track_voucher.html', payment=payment)
