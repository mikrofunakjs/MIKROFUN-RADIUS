"""Reseller Admin Management Blueprint"""
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from web.database import execute_query
from web.decorators import admin_required

reseller_admin_bp = Blueprint('reseller_admin', __name__)

@reseller_admin_bp.route('/')
@admin_required
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    query = (
        "SELECT u.*, "
        "(SELECT COUNT(*) FROM vouchers v WHERE v.reseller_id = u.id) as total_vouchers "
        "FROM users u WHERE u.role = 'reseller' ORDER BY u.created_at DESC"
    )
    resellers = execute_query(query, fetch=True) or []
    
    row_color = execute_query("SELECT setting_value FROM settings WHERE setting_key='reseller_theme_color'", fetch_one=True)
    current_theme_color = row_color['setting_value'] if row_color else '#4f46e5'
    return render_template('reseller_admin/list.html', resellers=resellers, current_theme_color=current_theme_color)

@reseller_admin_bp.route('/add', methods=['GET', 'POST'])
@admin_required
def add():
    if not session.get('logged_in'): return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        discount = request.form.get('discount_percent', 0)
        
        try:
            execute_query(
                "INSERT INTO users (username, password, role, discount_percent, balance) VALUES (%s, %s, 'reseller', %s, 0)",
                (username, password, discount)
            )
            flash('Mitra / Reseller berhasil ditambahkan!', 'success')
            return redirect(url_for('reseller_admin.index'))
        except Exception as e:
            flash(f'Gagal menambahkan Mitra: {str(e)}', 'error')
            
    return render_template('reseller_admin/add.html')

@reseller_admin_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit(id):
    if not session.get('logged_in'): return redirect(url_for('auth.login'))
    reseller = execute_query("SELECT * FROM users WHERE id=%s AND role='reseller'", (id,), fetch_one=True)
    if not reseller:
        flash('Data Mitra tidak ditemukan.', 'error')
        return redirect(url_for('reseller_admin.index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        discount = request.form.get('discount_percent', 0)
        
        if password:
            execute_query(
                "UPDATE users SET username=%s, password=%s, discount_percent=%s WHERE id=%s",
                (username, password, discount, id)
            )
        else:
             execute_query(
                "UPDATE users SET username=%s, discount_percent=%s WHERE id=%s",
                (username, discount, id)
            )
        flash('Data Mitra berhasil diupdate!', 'success')
        return redirect(url_for('reseller_admin.index'))
        
    return render_template('reseller_admin/edit.html', reseller=reseller)

@reseller_admin_bp.route('/topup/<int:id>', methods=['POST'])
@admin_required
def topup(id):
    if not session.get('logged_in'): return redirect(url_for('auth.login'))
    try:
        amount = float(request.form.get('amount', 0))
    except ValueError:
        flash('Nominal Top-Up harus berupa angka.', 'error')
        return redirect(url_for('reseller_admin.index'))
        
    desc = request.form.get('description', 'Manual Top-Up via Admin')
    
    if amount <= 0:
        flash('Nominal Top-Up harus lebih dari 0.', 'error')
        return redirect(url_for('reseller_admin.index'))
        
    reseller = execute_query("SELECT balance FROM users WHERE id=%s AND role='reseller'", (id,), fetch_one=True)
    if not reseller:
        flash('Data Mitra tidak ditemukan.', 'error')
        return redirect(url_for('reseller_admin.index'))
        
    balance_before = float(reseller['balance'] or 0)
    balance_after = balance_before + amount
    
    try:
        execute_query("UPDATE users SET balance = %s WHERE id = %s", (balance_after, id))
        execute_query(
            "INSERT INTO reseller_transactions (reseller_id, type, amount, description, balance_before, balance_after) VALUES (%s, 'topup', %s, %s, %s, %s)",
            (id, amount, desc, balance_before, balance_after)
        )
        # ── FINANCE LEDGER: catat deposit mitra masuk ke kas ISP ──────────
        try:
            from web.finance_helper import record_mitra_deposit
            r = execute_query("SELECT username FROM users WHERE id=%s", (id,), fetch_one=True)
            record_mitra_deposit(id, r['username'] if r else f'ID-{id}', amount, desc)
        except Exception as _fe:
            print(f"[finance] warn: {_fe}")
        # ─────────────────────────────────────────────────────────────────
        flash(f'Top-Up Rp {amount:,.0f} berhasil! Saldo saat ini: Rp {balance_after:,.0f}', 'success')
    except Exception as e:
        flash(f'Gagal memproses Top-Up: {str(e)}', 'error')
        
    return redirect(url_for('reseller_admin.index'))

@reseller_admin_bp.route('/delete/<int:id>')
@admin_required
def delete(id):
    if not session.get('logged_in'): return redirect(url_for('auth.login'))
    execute_query("DELETE FROM users WHERE id=%s AND role='reseller'", (id,))
    flash('Mitra berhasil dihapus!', 'success')
    return redirect(url_for('reseller_admin.index'))

@reseller_admin_bp.route('/report/<int:id>')
@admin_required
def report(id):
    """View full transaction + voucher log for a specific reseller"""
    if not session.get('logged_in'): return redirect(url_for('auth.login'))
    
    reseller = execute_query("SELECT * FROM users WHERE id=%s AND role='reseller'", (id,), fetch_one=True)
    if not reseller:
        flash('Data Mitra tidak ditemukan.', 'error')
        return redirect(url_for('reseller_admin.index'))
    
    transactions = execute_query(
        "SELECT * FROM reseller_transactions WHERE reseller_id=%s ORDER BY created_at DESC",
        (id,), fetch=True
    ) or []
    
    vouchers = execute_query(
        "SELECT v.*, p.name as profile_name FROM vouchers v "
        "LEFT JOIN profiles p ON v.profile_id = p.id "
        "WHERE v.reseller_id=%s ORDER BY v.created_at DESC",
        (id,), fetch=True
    ) or []
    
    total_topup = sum(float(t['amount']) for t in transactions if t['type'] == 'topup')
    total_purchases = sum(float(t['amount']) for t in transactions if t['type'] == 'purchase')
    total_profit_est = sum(float(v.get('price', 0)) - float(v.get('buy_price', 0)) for v in vouchers)
    
    return render_template(
        'reseller_admin/report.html',
        reseller=reseller,
        transactions=transactions,
        vouchers=vouchers,
        total_topup=total_topup,
        total_purchases=total_purchases,
        total_profit_est=total_profit_est
    )

@reseller_admin_bp.route('/theme', methods=['POST'])
@admin_required
def save_theme():
    if not session.get('logged_in'): return redirect(url_for('auth.login'))
    color = request.form.get('theme_color', '#4f46e5').strip()
    if color.startswith('#') and len(color) in [4, 7]:
        existing = execute_query("SELECT id FROM settings WHERE setting_key='reseller_theme_color'", fetch_one=True)
        if existing:
            execute_query("UPDATE settings SET setting_value=%s WHERE setting_key='reseller_theme_color'", (color,))
        else:
            execute_query("INSERT INTO settings (setting_key, setting_value) VALUES ('reseller_theme_color', %s)", (color,))
        flash(f'Tema warna berhasil diubah ke {color}', 'success')
    else:
        flash('Format warna tidak valid.', 'error')
    return redirect(url_for('reseller_admin.index'))

