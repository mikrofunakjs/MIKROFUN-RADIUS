"""Logs Blueprint - View Application Error & Activity Logs"""
from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify
from web.database import execute_query
from web.decorators import cs_or_admin_required

logs_bp = Blueprint('logs', __name__)

@logs_bp.route('/', methods=['GET'])
@cs_or_admin_required
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    level_filter = request.args.get('level', '')
    q = request.args.get('q', '')
    page = max(1, int(request.args.get('page', 1)))
    per_page = 50
    offset = (page - 1) * per_page

    query = "SELECT * FROM app_logs WHERE 1=1"
    count_query = "SELECT COUNT(*) as c FROM app_logs WHERE 1=1"
    params = []

    if level_filter:
        query += " AND level = %s"
        count_query += " AND level = %s"
        params.append(level_filter.upper())

    if q:
        query += " AND (message LIKE %s OR detail LIKE %s)"
        count_query += " AND (message LIKE %s OR detail LIKE %s)"
        params.extend([f"%{q}%", f"%{q}%"])

    query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"

    logs = execute_query(query, tuple(params) + (per_page, offset), fetch=True) or []
    total = (execute_query(count_query, tuple(params), fetch_one=True) or {}).get('c', 0)
    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template('logs/index.html',
                           logs=logs,
                           level_filter=level_filter,
                           q=q,
                           page=page,
                           total_pages=total_pages,
                           total=total)


@logs_bp.route('/clear', methods=['POST'])
@cs_or_admin_required
def clear():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    level = request.form.get('level', '')
    if level:
        execute_query("DELETE FROM app_logs WHERE level = %s", (level.upper(),))
    else:
        execute_query("DELETE FROM app_logs")
    from flask import flash
    flash('Log berhasil dibersihkan.', 'success')
    return redirect(url_for('logs.index'))
