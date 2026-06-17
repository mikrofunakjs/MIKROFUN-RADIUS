from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from web.database import execute_query
from web.decorators import admin_required
from datetime import date
import re

inventory_bp = Blueprint('inventory', __name__)

ALLOWED_CATEGORIES = ('modem', 'router', 'tool', 'other')
ALLOWED_ENTITY_TYPES = ('technician', 'customer')
MAC_RE = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$')

@inventory_bp.route('/')
@admin_required
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    assets = execute_query(
        "SELECT a.*, "
        "COALESCE(tu.username, c.name, '-') as assignee_name "
        "FROM assets a "
        "LEFT JOIN users tu ON a.assigned_to_type = 'technician' AND a.assigned_to_id = tu.id "
        "LEFT JOIN customers c ON a.assigned_to_type = 'customer' AND a.assigned_to_id = c.id "
        "ORDER BY a.id DESC",
        fetch=True
    ) or []

    total = len(assets)
    available = sum(1 for a in assets if a.get('status') == 'available')
    assigned = sum(1 for a in assets if a.get('status') in ('assigned_tech', 'assigned_cust'))
    broken = sum(1 for a in assets if a.get('status') in ('broken', 'lost'))

    stats = {'total': total, 'available': available, 'assigned': assigned, 'broken': broken}

    techs = execute_query(
        "SELECT id, username as name FROM users WHERE role IN ('technician', 'admin') ORDER BY username ASC",
        fetch=True
    ) or []

    customers = execute_query(
        "SELECT id, username, name FROM customers ORDER BY name ASC",
        fetch=True
    ) or []

    return render_template('inventory/index.html', assets=assets, stats=stats, techs=techs, customers=customers)

@inventory_bp.route('/assign/<int:id>', methods=['POST'])
@admin_required
def assign(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    entity_type = request.form.get('entity_type', '').strip()
    entity_id_str = request.form.get('entity_id', '').strip()
    notes = request.form.get('notes', '').strip()

    if entity_type not in ALLOWED_ENTITY_TYPES:
        flash("Jenis penerima tidak valid.", "error")
        return redirect(url_for('inventory.index'))

    if not entity_id_str or not entity_id_str.isdigit():
        flash("ID penerima tidak valid.", "error")
        return redirect(url_for('inventory.index'))

    entity_id = int(entity_id_str)

    # Check asset exists and is available
    asset = execute_query("SELECT * FROM assets WHERE id=%s", (id,), fetch_one=True)
    if not asset:
        flash("Aset tidak ditemukan.", "error")
        return redirect(url_for('inventory.index'))

    if asset['status'] != 'available':
        flash(f"Aset sedang dalam status '{asset['status']}', tidak bisa ditugaskan.", "error")
        return redirect(url_for('inventory.index'))

    # Check target entity exists
    if entity_type == 'technician':
        target = execute_query("SELECT id FROM users WHERE id=%s", (entity_id,), fetch_one=True)
    else:
        target = execute_query("SELECT id FROM customers WHERE id=%s", (entity_id,), fetch_one=True)

    if not target:
        flash(f"Target penerima (ID: {entity_id}) tidak ditemukan.", "error")
        return redirect(url_for('inventory.index'))

    status_to_set = 'assigned_tech' if entity_type == 'technician' else 'assigned_cust'

    rows = execute_query(
        "UPDATE assets SET status=%s, assigned_to_type=%s, assigned_to_id=%s WHERE id=%s AND status='available'",
        (status_to_set, entity_type, entity_id, id)
    )
    if not rows or rows == 0:
        flash("Aset sudah ditugaskan oleh admin lain.", "warning")
        return redirect(url_for('inventory.index'))

    execute_query(
        "INSERT INTO asset_logs (asset_id, action, entity_type, entity_id, admin_id, notes) VALUES (%s, 'assign', %s, %s, %s, %s)",
        (id, entity_type, entity_id, session.get('user_id'), notes)
    )
    flash("Aset berhasil ditugaskan/dipinjamkan.", "success")
    return redirect(url_for('inventory.index'))

@inventory_bp.route('/return/<int:id>', methods=['POST'])
@admin_required
def return_asset(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    condition = request.form.get('condition', '').strip()
    notes = request.form.get('notes', '').strip()

    asset = execute_query("SELECT * FROM assets WHERE id=%s", (id,), fetch_one=True)
    if not asset:
        flash("Aset tidak ditemukan.", "error")
        return redirect(url_for('inventory.index'))

    if asset['status'] not in ('assigned_tech', 'assigned_cust'):
        flash("Aset tidak sedang dipinjamkan/ditugaskan.", "error")
        return redirect(url_for('inventory.index'))

    new_status = 'available'
    log_action = 'return'

    if condition == 'broken':
        new_status = 'broken'
        log_action = 'mark_broken'
    elif condition == 'lost':
        new_status = 'lost'
        log_action = 'mark_lost'

    rows = execute_query(
        "UPDATE assets SET status=%s, assigned_to_type=NULL, assigned_to_id=NULL WHERE id=%s AND status IN ('assigned_tech','assigned_cust')",
        (new_status, id)
    )
    if not rows or rows == 0:
        flash("Aset sudah dikembalikan oleh admin lain.", "warning")
        return redirect(url_for('inventory.index'))

    execute_query(
        "INSERT INTO asset_logs (asset_id, action, entity_type, entity_id, admin_id, notes) VALUES (%s, %s, %s, %s, %s, %s)",
        (id, log_action, asset['assigned_to_type'], asset['assigned_to_id'], session.get('user_id'), notes)
    )

    flash("Status aset berhasil diperbarui (masuk gudang).", "success")
    return redirect(url_for('inventory.index'))

@inventory_bp.route('/repair/<int:id>', methods=['POST'])
@admin_required
def repair(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    asset = execute_query("SELECT * FROM assets WHERE id=%s AND status IN ('broken', 'lost')", (id,), fetch_one=True)
    if not asset:
        flash("Aset tidak ditemukan atau tidak dalam status rusak/hilang.", "error")
        return redirect(url_for('inventory.index'))

    notes = request.form.get('notes', 'Dipulihkan ke gudang').strip()

    rows = execute_query(
        "UPDATE assets SET status='available', assigned_to_type=NULL, assigned_to_id=NULL WHERE id=%s AND status IN ('broken','lost')",
        (id,)
    )
    if not rows or rows == 0:
        flash("Aset sudah dipulihkan oleh admin lain.", "warning")
        return redirect(url_for('inventory.index'))

    execute_query(
        "INSERT INTO asset_logs (asset_id, action, entity_type, entity_id, admin_id, notes) VALUES (%s, 'repaired', %s, %s, %s, %s)",
        (id, asset['assigned_to_type'], asset['assigned_to_id'], session.get('user_id'), notes)
    )
    flash("Aset dikembalikan ke gudang.", "success")
    return redirect(url_for('inventory.index'))

@inventory_bp.route('/add', methods=['GET', 'POST'])
@admin_required
def add():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        brand = request.form.get('brand', '').strip()
        mac_address = request.form.get('mac_address', '').strip()
        serial_number = request.form.get('serial_number', '').strip()
        purchase_price_str = request.form.get('purchase_price', '0').strip()
        purchase_date_str = request.form.get('purchase_date', '').strip()
        notes = request.form.get('notes', '').strip()

        errors = []

        if not name or len(name) < 2:
            errors.append("Nama barang wajib diisi (minimal 2 karakter).")
        if len(name) > 128:
            errors.append("Nama barang maksimal 128 karakter.")

        if category not in ALLOWED_CATEGORIES:
            errors.append("Kategori tidak valid.")

        try:
            purchase_price = float(purchase_price_str)
            if purchase_price < 0:
                errors.append("Harga pembelian tidak boleh negatif.")
        except (ValueError, TypeError):
            errors.append("Harga pembelian harus berupa angka.")

        purchase_date = None
        if purchase_date_str:
            try:
                purchase_date = date.fromisoformat(purchase_date_str)
                if purchase_date > date.today():
                    errors.append("Tanggal pembelian tidak boleh di masa depan.")
            except ValueError:
                errors.append("Format tanggal pembelian tidak valid.")

        if mac_address and not MAC_RE.match(mac_address):
            errors.append("Format MAC Address tidak valid (contoh: 00:11:22:33:44:55).")

        if serial_number:
            existing = execute_query(
                "SELECT id FROM assets WHERE serial_number=%s LIMIT 1",
                (serial_number,), fetch_one=True
            )
            if existing:
                errors.append("Serial Number sudah terdaftar di aset lain.")

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template('inventory/add.html')

        try:
            execute_query(
                "INSERT INTO assets (name, category, brand, mac_address, serial_number, purchase_price, purchase_date, status, notes) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'available', %s)",
                (name, category, brand, mac_address, serial_number, purchase_price, purchase_date, notes)
            )
            flash("Aset berhasil ditambahkan.", "success")
        except Exception:
            flash("Gagal menambahkan aset. Silakan coba lagi.", "error")

        return redirect(url_for('inventory.index'))

    return render_template('inventory/add.html')

@inventory_bp.route('/delete/<int:id>', methods=['POST'])
@admin_required
def delete(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    asset = execute_query("SELECT * FROM assets WHERE id=%s", (id,), fetch_one=True)
    if not asset:
        flash("Aset tidak ditemukan.", "error")
        return redirect(url_for('inventory.index'))

    execute_query(
        "INSERT INTO asset_logs (asset_id, action, entity_type, entity_id, admin_id, notes) VALUES (%s, 'deleted', %s, %s, %s, %s)",
        (id, asset.get('assigned_to_type'), asset.get('assigned_to_id'),
         session.get('user_id'), f"Aset '{asset['name']}' dihapus dari sistem")
    )
    execute_query("DELETE FROM assets WHERE id=%s", (id,))
    flash("Aset dihapus.", "success")
    return redirect(url_for('inventory.index'))

@inventory_bp.route('/logs/<int:id>')
@admin_required
def logs(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    asset = execute_query("SELECT * FROM assets WHERE id=%s", (id,), fetch_one=True)
    if not asset:
        return redirect(url_for('inventory.index'))

    logs = execute_query(
        "SELECT l.*, u.username as admin_name, "
        "CASE "
        "  WHEN l.entity_type = 'technician' THEN tu.username "
        "  WHEN l.entity_type = 'customer' THEN c.name "
        "  ELSE '-' "
        "END as entity_name "
        "FROM asset_logs l "
        "LEFT JOIN users u ON l.admin_id = u.id "
        "LEFT JOIN users tu ON l.entity_type = 'technician' AND l.entity_id = tu.id "
        "LEFT JOIN customers c ON l.entity_type = 'customer' AND l.entity_id = c.id "
        "WHERE l.asset_id=%s ORDER BY l.action_date DESC",
        (id,), fetch=True
    ) or []

    return render_template('inventory/logs.html', asset=asset, logs=logs)
