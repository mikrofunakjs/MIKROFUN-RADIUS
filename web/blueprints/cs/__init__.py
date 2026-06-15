from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from web.database import execute_query
from web.decorators import cs_or_admin_required
import datetime

cs_bp = Blueprint('cs', __name__)

@cs_bp.route('/dashboard')
@cs_or_admin_required
def dashboard():
    # Merge customer stats into single query
    cust_stats = execute_query(
        "SELECT "
        "SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) as active, "
        "SUM(CASE WHEN status IN ('isolated','isolir') THEN 1 ELSE 0 END) as isolated "
        "FROM customers",
        fetch_one=True
    ) or {}
    active_cust = cust_stats.get('active', 0)
    iso_cust = cust_stats.get('isolated', 0)

    # Merge ticket + voucher counts
    pending_stats = execute_query(
        "SELECT "
        "(SELECT COUNT(*) FROM tickets WHERE status='open') as open_tickets, "
        "(SELECT COUNT(*) FROM payments WHERE payment_type='voucher' AND status='pending') as pending_vouchers",
        fetch_one=True
    ) or {}
    open_tickets = pending_stats.get('open_tickets', 0)
    pending_vouchers = pending_stats.get('pending_vouchers', 0)

    stats = {
        'active_customers': active_cust,
        'isolated_customers': iso_cust,
        'open_tickets': open_tickets,
        'pending_vouchers': pending_vouchers
    }

    recent_tickets = execute_query(
        "SELECT t.*, c.name as customer_name "
        "FROM tickets t "
        "LEFT JOIN customers c ON t.customer_id = c.id "
        "ORDER BY t.created_at DESC LIMIT 5",
        fetch=True
    ) or []

    return render_template('cs/dashboard.html', stats=stats, tickets=recent_tickets, title='CS Dashboard')
