from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from web.database import execute_query
from web.decorators import cs_or_admin_required, admin_required

helpdesk_bp = Blueprint('helpdesk', __name__)

@helpdesk_bp.route('/', methods=['GET'])
@cs_or_admin_required
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    tickets = execute_query(
        "SELECT t.*, c.name as customer_name, c.username "
        "FROM tickets t "
        "LEFT JOIN customers c ON t.customer_id = c.id "
        "ORDER BY FIELD(t.status, 'open', 'answered', 'closed'), t.updated_at DESC",
        fetch=True
    ) or []

    return render_template('helpdesk/index.html', tickets=tickets)

@helpdesk_bp.route('/add', methods=['GET', 'POST'])
@cs_or_admin_required
def add():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        customer_id_str = request.form.get('customer_id', '').strip()
        subject = request.form.get('subject', '').strip()[:200]
        category = request.form.get('category', 'General').strip()[:64]
        priority = request.form.get('priority', 'medium').strip()
        message = request.form.get('message', '').strip()[:5000]

        if not customer_id_str or not subject or not message:
            flash('Pelanggan, subject, dan pesan wajib diisi.', 'error')
            customers = execute_query("SELECT id, name, username FROM customers ORDER BY name ASC", fetch=True) or []
            return render_template('helpdesk/add.html', customers=customers)

        if priority not in ('low', 'medium', 'high'):
            priority = 'medium'

        # Validate customer exists
        cust = execute_query("SELECT id FROM customers WHERE id=%s", (customer_id_str,), fetch_one=True)
        if not cust:
            flash('Pelanggan tidak ditemukan.', 'error')
            customers = execute_query("SELECT id, name, username FROM customers ORDER BY name ASC", fetch=True) or []
            return render_template('helpdesk/add.html', customers=customers)

        ticket_id = execute_query(
            "INSERT INTO tickets (customer_id, subject, category, priority, status) VALUES (%s, %s, %s, %s, 'open')",
            (int(customer_id_str), subject, category, priority)
        )

        if ticket_id:
            execute_query(
                "INSERT INTO ticket_replies (ticket_id, sender_type, sender_id, message) VALUES (%s, 'admin', %s, %s)",
                (ticket_id, session.get('user_id') or 0, message)
            )
            flash('Tiket berhasil dibuat.', 'success')
        else:
            flash('Gagal membuat tiket. Silakan coba lagi.', 'error')

        return redirect(url_for('helpdesk.index'))

    customers = execute_query("SELECT id, name, username FROM customers ORDER BY name ASC", fetch=True) or []
    return render_template('helpdesk/add.html', customers=customers)

@helpdesk_bp.route('/view/<int:id>', methods=['GET', 'POST'])
@cs_or_admin_required
def view(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    ticket = execute_query(
        "SELECT t.*, c.name as customer_name, c.username, c.id as uid "
        "FROM tickets t "
        "LEFT JOIN customers c ON t.customer_id = c.id "
        "WHERE t.id=%s", (id,), fetch_one=True
    )
    if not ticket:
        flash('Tiket tidak ditemukan.', 'error')
        return redirect(url_for('helpdesk.index'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'reply':
            message = request.form.get('message', '').strip()[:5000]
            if message:
                execute_query(
                    "INSERT INTO ticket_replies (ticket_id, sender_type, sender_id, message) VALUES (%s, 'admin', %s, %s)",
                    (id, session.get('user_id') or 0, message)
                )
                execute_query("UPDATE tickets SET status='answered', updated_at=NOW() WHERE id=%s", (id,))
                flash('Balasan terkirim.', 'success')
            else:
                flash('Pesan balasan tidak boleh kosong.', 'error')

        elif action == 'close':
            execute_query("UPDATE tickets SET status='closed' WHERE id=%s", (id,))
            flash('Tiket ditutup.', 'success')

        elif action == 'delete':
            if session.get('role') != 'admin':
                flash('Hanya admin yang dapat menghapus tiket.', 'error')
            else:
                execute_query("DELETE FROM ticket_replies WHERE ticket_id=%s", (id,))
                execute_query("DELETE FROM tickets WHERE id=%s", (id,))
                flash('Tiket dihapus.', 'success')
                return redirect(url_for('helpdesk.index'))

        return redirect(url_for('helpdesk.view', id=id))

    replies = execute_query(
        "SELECT r.*, u.username as admin_name "
        "FROM ticket_replies r "
        "LEFT JOIN users u ON r.sender_type = 'admin' AND r.sender_id = u.id "
        "WHERE r.ticket_id=%s ORDER BY r.created_at ASC",
        (id,), fetch=True
    ) or []

    return render_template('helpdesk/view.html', ticket=ticket, replies=replies)

@helpdesk_bp.route('/dispatch_job/<int:ticket_id>')
@cs_or_admin_required
def dispatch_job(ticket_id):
    ticket = execute_query(
        "SELECT t.*, c.name as customer_name FROM tickets t "
        "LEFT JOIN customers c ON t.customer_id = c.id WHERE t.id=%s",
        (ticket_id,), fetch_one=True
    )
    if not ticket:
        flash('Tiket tidak ditemukan.', 'error')
        return redirect(url_for('helpdesk.index'))

    first_reply = execute_query(
        "SELECT message FROM ticket_replies WHERE ticket_id=%s ORDER BY created_at ASC LIMIT 1",
        (ticket_id,), fetch_one=True
    )
    desc = first_reply['message'] if first_reply else ''

    return redirect(url_for('dispatch.index',
                           ticket_id=ticket['id'],
                           cust_id=ticket.get('customer_id', ''),
                           title=f"Perbaikan: {ticket['subject']}",
                           desc=desc[:500]))
