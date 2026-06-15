from flask import Blueprint, render_template, request, session, redirect, url_for, flash
import datetime
from dateutil.relativedelta import relativedelta
from web.database import execute_query
from web.decorators import cs_or_admin_required, admin_required

billing_bp = Blueprint('billing', __name__)

def _fmt(v):
    return '{:,.0f}'.format(float(v)).replace(',', '.')

def _safe_name(name):
    if not name:
        return ''
    return name.replace('{', '{{').replace('}', '}}')

def _safe_msg(msg):
    return msg.replace('{', '{{').replace('}', '}}')

@billing_bp.route('/', methods=['GET'])
@cs_or_admin_required
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    AUTO_CHANNELS = ("'MIDTRANS'", "'TRIPAY'", "'DUITKU'", "'MOOTA'")
    auto_channels_str = ", ".join(AUTO_CHANNELS)

    manual_pending = execute_query(
        "SELECT p.*, c.name as customer_name, c.username "
        "FROM payments p "
        "LEFT JOIN customers c ON p.customer_id = c.id "
        f"WHERE p.status = 'pending' AND (p.payment_channel IS NULL OR p.payment_channel = '' OR p.payment_channel NOT IN ({auto_channels_str})) "
        "ORDER BY p.payment_date ASC",
        fetch=True
    ) or []

    manual_history = execute_query(
        "SELECT p.*, c.name as customer_name "
        "FROM payments p "
        "LEFT JOIN customers c ON p.customer_id = c.id "
        f"WHERE p.status NOT IN ('pending', 'processing') AND (p.payment_channel IS NULL OR p.payment_channel = '' OR p.payment_channel NOT IN ({auto_channels_str})) "
        "ORDER BY p.created_at DESC LIMIT 50",
        fetch=True
    ) or []

    gateway_transactions = execute_query(
        "SELECT p.*, c.name as customer_name, c.username "
        "FROM payments p "
        "LEFT JOIN customers c ON p.customer_id = c.id "
        f"WHERE p.payment_channel IN ({auto_channels_str}) "
        "ORDER BY p.created_at DESC LIMIT 50",
        fetch=True
    ) or []

    banks = execute_query("SELECT * FROM bank_accounts WHERE is_active=1", fetch=True) or []
    customers = execute_query("SELECT id, name, username FROM customers ORDER BY name ASC", fetch=True) or []

    return render_template(
        'billing/index.html',
        manual_pending=manual_pending,
        manual_history=manual_history,
        gateway_transactions=gateway_transactions,
        banks=banks,
        customers=customers
    )

@billing_bp.route('/confirm/<int:id>', methods=['POST'])
@cs_or_admin_required
def confirm_payment(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    pid = id
    rows = execute_query(
        "UPDATE payments SET status='processing' WHERE id=%s AND status='pending'",
        (pid,)
    )
    if not rows or rows == 0:
        flash('Transaksi tidak ditemukan, sudah diproses, atau sedang diproses.', 'warning')
        return redirect(url_for('billing.index'))

    payment = execute_query("SELECT * FROM payments WHERE id=%s", (pid,), fetch_one=True)
    if not payment:
        flash('Transaksi tidak ditemukan.', 'error')
        return redirect(url_for('billing.index'))

    _activate_from_payment(payment)
    flash('Pembayaran berhasil dikonfirmasi.', 'success')
    return redirect(url_for('billing.index'))

@billing_bp.route('/pos', methods=['POST'])
@cs_or_admin_required
def pos():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    customer_id = request.form.get('customer_id', '').strip()
    amount_str = request.form.get('amount', '').strip()
    notes = request.form.get('notes', '').strip()

    if not customer_id or not amount_str:
        flash('Customer dan jumlah pembayaran wajib diisi.', 'error')
        return redirect(url_for('billing.index'))

    if not customer_id.isdigit():
        flash('ID Customer tidak valid.', 'error')
        return redirect(url_for('billing.index'))

    cid = int(customer_id)

    try:
        amount = float(amount_str)
        if amount <= 0:
            flash('Jumlah pembayaran harus lebih dari Rp 0.', 'error')
            return redirect(url_for('billing.index'))
    except (ValueError, TypeError):
        flash('Jumlah pembayaran tidak valid.', 'error')
        return redirect(url_for('billing.index'))

    # 0. Validate customer exists FIRST
    customer = execute_query(
        "SELECT c.*, p.price as profile_price FROM customers c "
        "LEFT JOIN profiles p ON c.profile_id = p.id WHERE c.id=%s",
        (cid,), fetch_one=True
    )
    if not customer:
        flash('Customer tidak ditemukan.', 'error')
        return redirect(url_for('billing.index'))

    # Warn if amount is significantly lower than profile price
    profile_price = float(customer.get('profile_price', 0) or 0)
    if profile_price > 0 and amount < profile_price * 0.5:
        flash(
            f'Perhatian: Pembayaran Rp {_fmt(amount)} lebih rendah dari tagihan normal Rp {_fmt(profile_price)}.',
            'warning'
        )

    # 1. Insert Payment (Approved directly)
    result = execute_query(
        "INSERT INTO payments (customer_id, amount, sender_bank, sender_name, payment_date, status) "
        "VALUES (%s, %s, 'CASH', 'POS ADMIN', NOW(), 'approved')",
        (cid, amount)
    )
    payment_id = result if isinstance(result, int) else None

    # FINANCE LEDGER
    try:
        from web.finance_helper import record_client_payment
        _payment_dict = {
            'id': payment_id,
            'customer_id': cid,
            'amount': amount,
            'payment_channel': 'POS / Tunai',
            'external_ref': f"POS-{cid}-{int(datetime.datetime.now().timestamp())}",
        }
        record_client_payment(_payment_dict, _safe_name(customer.get('name', '')))
    except Exception as _fe:
        print(f"[finance] warn POS: {_fe}")

    # 2. Update Customer
    updates = []
    params = []

    if customer['status'] == 'isolir':
        updates.append("status='active'")

    today = datetime.date.today()
    current_due = customer.get('due_date')

    if not current_due or current_due < today:
        new_due = today + relativedelta(months=1)
    else:
        new_due = current_due + relativedelta(months=1)

    updates.append("due_date=%s")
    params.append(new_due)

    sql = f"UPDATE customers SET {', '.join(updates)} WHERE id=%s"
    params.append(customer['id'])
    execute_query(sql, tuple(params))

    # WA Notification
    try:
        if customer.get('phone'):
            from web.wa_helper import send_wa
            name = _safe_name(customer.get('name', 'Pelanggan'))
            msg = (f"Halo {name},\n"
                   f"Pembayaran tunai sebesar Rp {_fmt(amount)} telah diterima via Loket Admin.\n"
                   f"Masa aktif diperpanjang hingga {new_due.strftime('%d/%m/%Y')}.\n"
                   f"Terima kasih.")
            send_wa(customer['phone'], msg)
    except Exception as e:
        print(f"WA Notification Failed (POS): {e}")

    flash('Pembayaran manual berhasil dicatat.', 'success')
    return redirect(url_for('billing.index'))

def _activate_from_payment(payment):
    """Common activation logic after payment is approved. Assumes payment is already claimed."""
    pid = payment.get('id')

    # Finance Ledger
    try:
        customer_name = '-'
        if payment.get('customer_id'):
            c = execute_query("SELECT name FROM customers WHERE id=%s", (payment['customer_id'],), fetch_one=True)
            customer_name = _safe_name(c['name']) if c else f"ID-{payment['customer_id']}"
        elif payment.get('guest_phone'):
            customer_name = 'Guest (Public Voucher)'
        from web.finance_helper import record_client_payment
        record_client_payment(payment, customer_name)
    except Exception as _fe:
        print(f"[finance] warn: {_fe}")

    # Voucher Auto-Gen
    if payment.get('payment_type') == 'voucher':
        from web.blueprints.api import generate_voucher_for_payment
        voucher_code = generate_voucher_for_payment(payment)
        execute_query(
            "UPDATE payments SET status='approved', payment_date=NOW(), voucher_code=%s WHERE id=%s",
            (voucher_code, pid)
        )
        return

    # Customer Extend
    if not payment.get('customer_id'):
        print(f"[billing] Payment {pid} has no customer_id, marking approved only")
        execute_query("UPDATE payments SET status='approved', payment_date=NOW() WHERE id=%s", (pid,))
        return

    customer = execute_query("SELECT * FROM customers WHERE id=%s", (payment['customer_id'],), fetch_one=True)
    if not customer:
        print(f"[billing] Customer {payment.get('customer_id')} not found for payment {pid}")
        execute_query("UPDATE payments SET status='approved', payment_date=NOW() WHERE id=%s", (pid,))
        return

    today = datetime.date.today()
    current_due = customer.get('due_date')

    if not current_due or current_due < today:
        new_due = today + relativedelta(months=1)
    else:
        new_due = current_due + relativedelta(months=1)

    status_update = "status='active', " if customer['status'] == 'isolir' else ""
    execute_query(
        f"UPDATE customers SET {status_update}due_date=%s WHERE id=%s",
        (new_due, customer['id'])
    )

    # Mark payment approved
    execute_query("UPDATE payments SET status='approved', payment_date=NOW() WHERE id=%s", (pid,))

    # WA Notification
    try:
        if customer.get('phone'):
            from web.wa_helper import send_wa
            name = _safe_name(customer.get('name', 'Pelanggan'))
            msg = (f"Halo {name},\n"
                   f"Pembayaran sebesar Rp {_fmt(payment.get('amount', 0))} telah DITERIMA.\n"
                   f"Masa aktif paket internet Anda diperpanjang hingga {new_due.strftime('%d/%m/%Y')}.\n"
                   f"Terima kasih. - MikroFun Team")
            send_wa(customer['phone'], msg)
    except:
        pass

def _approve_logic(pid):
    rows = execute_query(
        "UPDATE payments SET status='processing' WHERE id=%s AND status='pending'",
        (pid,)
    )
    if rows is None:
        print(f"[billing] approve({pid}): DB error!")
        return False
    if rows == 0:
        print(f"[billing] approve({pid}): payment not found or not pending (rowcount=0)")
        return False

    payment = execute_query("SELECT * FROM payments WHERE id=%s", (pid,), fetch_one=True)
    if not payment:
        print(f"[billing] approve({pid}): payment vanished after lock")
        return False

    if float(payment.get('amount', 0)) <= 0:
        execute_query("UPDATE payments SET status='rejected' WHERE id=%s", (pid,))
        print(f"[billing] Payment {pid} rejected: zero/negative amount")
        return False

    _activate_from_payment(payment)
    print(f"[billing] approve({pid}): SUCCESS")
    return True

def _reject_logic(pid):
    execute_query(
        "UPDATE payments SET status='rejected' WHERE id=%s AND status IN ('pending','processing')",
        (pid,)
    )
    payment = execute_query("SELECT * FROM payments WHERE id=%s AND status='rejected'", (pid,), fetch_one=True)
    if not payment:
        print(f"[billing] reject({pid}): payment not found or not pending/processing")
        return False

    try:
        if payment.get('customer_id'):
            customer = execute_query("SELECT * FROM customers WHERE id=%s", (payment['customer_id'],), fetch_one=True)
            if customer and customer.get('phone'):
                from web.wa_helper import send_wa
                name = _safe_name(customer.get('name', 'Pelanggan'))
                msg = (f"Halo {name},\n"
                       f"Mohon maaf, pembayaran sebesar Rp {_fmt(payment.get('amount', 0))} DITOLAK.\n"
                       f"Silakan hubungi admin untuk info lebih lanjut.")
                send_wa(customer['phone'], msg)
    except:
        pass

    print(f"[billing] reject({pid}): SUCCESS")
    return True

@billing_bp.route('/bulk_action', methods=['POST'])
@cs_or_admin_required
def bulk_action():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    payment_ids = request.form.getlist('payment_ids')
    action = request.form.get('action')

    if not payment_ids:
        flash('Pilih transaksi terlebih dahulu.', 'warning')
        return redirect(url_for('billing.index'))

    success = 0
    failures = []
    for pid_str in payment_ids:
        try:
            pid = int(pid_str)
        except ValueError:
            failures.append(pid_str)
            continue
        try:
            if action == 'approve':
                _approve_logic(pid)
            else:
                _reject_logic(pid)
            success += 1
        except Exception as e:
            print(f"Bulk Error ID {pid}: {e}")
            failures.append(str(pid))

    if failures:
        flash(f'{success} berhasil, {len(failures)} gagal (ID: {", ".join(failures)}).', 'warning')
    else:
        flash(f'Berhasil memproses {success} transaksi.', 'success')
    return redirect(url_for('billing.index'))

@billing_bp.route('/approve/<int:id>')
@cs_or_admin_required
def approve(id):
    if _approve_logic(id):
        flash('Pembayaran disetujui. Lihat di Riwayat Pembayaran Manual.', 'success')
    else:
        flash('Pembayaran gagal disetujui. Cek log server atau periksa status transaksi.', 'error')
    return redirect(url_for('billing.index'))

@billing_bp.route('/reject/<int:id>')
@cs_or_admin_required
def reject(id):
    if _reject_logic(id):
        flash('Pembayaran ditolak.', 'warning')
    else:
        flash('Gagal menolak pembayaran.', 'error')
    return redirect(url_for('billing.index'))

@billing_bp.route('/bank/add', methods=['POST'])
@cs_or_admin_required
def add_bank():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    bank_name = request.form.get('bank_name', '').strip()[:64]
    account_number = request.form.get('account_number', '').strip()[:32]
    account_holder = request.form.get('account_holder', '').strip()[:128]

    if not bank_name or not account_number or not account_holder:
        flash('Semua field bank wajib diisi.', 'error')
        return redirect(url_for('billing.index'))

    execute_query(
        "INSERT INTO bank_accounts (bank_name, account_number, account_holder) VALUES (%s, %s, %s)",
        (bank_name, account_number, account_holder)
    )
    flash('Rekening baru ditambahkan.', 'success')
    return redirect(url_for('billing.index'))

@billing_bp.route('/bank/delete/<int:id>', methods=['POST'])
@cs_or_admin_required
def delete_bank(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    execute_query("DELETE FROM bank_accounts WHERE id=%s", (id,))
    flash('Rekening dihapus.', 'success')
    return redirect(url_for('billing.index'))

@billing_bp.route('/invoice/<int:payment_id>')
@cs_or_admin_required
def invoice(payment_id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    payment = execute_query(
        "SELECT p.*, c.name as customer_name, c.username, c.phone as customer_phone, "
        "c.address as customer_address, prof.name as profile_name "
        "FROM payments p "
        "LEFT JOIN customers c ON p.customer_id = c.id "
        "LEFT JOIN profiles prof ON c.profile_id = prof.id "
        "WHERE p.id=%s", (payment_id,), fetch_one=True
    )
    if not payment:
        flash('Invoice tidak ditemukan.', 'error')
        return redirect(url_for('billing.index'))

    company = {}
    rows = execute_query(
        "SELECT setting_key, setting_value FROM settings WHERE setting_key LIKE 'company_%'", fetch=True
    ) or []
    for r in rows:
        k = r['setting_key'].replace('company_', '')
        company[k] = r['setting_value']

    return render_template('billing/invoice.html', payment=payment, company=company)
