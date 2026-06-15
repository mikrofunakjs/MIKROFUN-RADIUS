from flask import Blueprint, render_template, request, session, redirect, url_for, make_response, flash
from web.database import execute_query
import datetime, csv, io

from web.decorators import admin_required

reports_bp = Blueprint('reports', __name__)


@reports_bp.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    # ── Date Filtering ───────────────────────────────────────────────────────
    start_date = request.args.get('start_date')
    end_date   = request.args.get('end_date')
    source_tab = request.args.get('tab', 'all')

    if not start_date:
        start_date = datetime.date.today().replace(day=1).strftime('%Y-%m-%d')
    if not end_date:
        end_date = datetime.date.today().strftime('%Y-%m-%d')

    # ── Summary Cards (from income_ledger) ───────────────────────────────────
    def _sum(col, where_extra='', params=()):
        q = (f"SELECT COALESCE(SUM({col}), 0) as total FROM income_ledger "
             f"WHERE DATE(created_at) BETWEEN %s AND %s {where_extra}")
        row = execute_query(q, (start_date, end_date) + params, fetch_one=True)
        return float(row['total']) if row else 0.0

    gross_total  = _sum('gross_amount')
    cost_total   = _sum('cost_amount')
    net_total    = _sum('net_profit')

    # Expenses totals for the period
    exp_row = execute_query(
        "SELECT COALESCE(SUM(amount),0) as total FROM expenses "
        "WHERE expense_date BETWEEN %s AND %s",
        (start_date, end_date), fetch_one=True
    )
    expense_total = float(exp_row['total']) if exp_row else 0.0
    real_profit   = round(net_total - expense_total, 2)

    # Per-source breakdown for summary
    breakdown = {}
    for src in ('admin_voucher', 'mitra_voucher', 'client_payment', 'mitra_deposit'):
        breakdown[src] = {
            'gross': _sum('gross_amount', "AND source_type=%s", (src,)),
            'cost':  _sum('cost_amount',  "AND source_type=%s", (src,)),
            'net':   _sum('net_profit',   "AND source_type=%s", (src,)),
        }

    # ── Chart: income + expenses per day ─────────────────────────────────────
    chart_rows = execute_query(
        "SELECT DATE(created_at) as day, COALESCE(SUM(net_profit),0) as daily_net "
        "FROM income_ledger "
        "WHERE DATE(created_at) BETWEEN %s AND %s "
        "GROUP BY DATE(created_at) ORDER BY day ASC",
        (start_date, end_date), fetch=True
    ) or []
    chart_labels = [str(r['day']) for r in chart_rows]
    chart_values = [float(r['daily_net']) for r in chart_rows]

    # ── Monthly Summary (P2: 12-month view) ──────────────────────────────────
    monthly_summary = execute_query(
        "SELECT DATE_FORMAT(created_at, '%Y-%m') as month, "
        "COALESCE(SUM(gross_amount),0) as gross, "
        "COALESCE(SUM(cost_amount),0) as cost, "
        "COALESCE(SUM(net_profit),0) as net, "
        "COUNT(*) as tx_count "
        "FROM income_ledger "
        "WHERE created_at >= DATE_SUB(NOW(), INTERVAL 12 MONTH) "
        "GROUP BY DATE_FORMAT(created_at, '%Y-%m') ORDER BY month DESC",
        fetch=True
    ) or []

    # Add expense per month to monthly_summary
    monthly_expenses = execute_query(
        "SELECT DATE_FORMAT(expense_date, '%Y-%m') as month, "
        "COALESCE(SUM(amount),0) as total_expense "
        "FROM expenses "
        "WHERE expense_date >= DATE_SUB(NOW(), INTERVAL 12 MONTH) "
        "GROUP BY DATE_FORMAT(expense_date, '%Y-%m')",
        fetch=True
    ) or []
    monthly_exp_map = {r['month']: float(r['total_expense']) for r in monthly_expenses}
    for row in monthly_summary:
        row['expense'] = monthly_exp_map.get(row['month'], 0.0)
        row['real_profit'] = round(float(row['net']) - row['expense'], 2)

    # ── Piutang / Outstanding (P2) ────────────────────────────────────────────
    piutang_list = execute_query(
        "SELECT p.id, p.amount, p.created_at, p.payment_type, "
        "c.name as customer_name, c.phone as customer_phone, "
        "c.due_date, pr.name as profile_name "
        "FROM payments p "
        "LEFT JOIN customers c ON p.customer_id = c.id "
        "LEFT JOIN profiles pr ON c.profile_id = pr.id "
        "WHERE p.status='pending' AND p.customer_id IS NOT NULL "
        "ORDER BY p.created_at ASC LIMIT 200",
        fetch=True
    ) or []
    piutang_total = sum(float(r['amount'] or 0) for r in piutang_list)

    # ── Transaction List (per tab) ────────────────────────────────────────────
    where_tab  = "AND source_type=%s" if source_tab not in ('all','piutang','monthly','expenses') else ""
    tab_params = (source_tab,) if source_tab not in ('all','piutang','monthly','expenses') else ()

    transactions = execute_query(
        "SELECT * FROM income_ledger "
        f"WHERE DATE(created_at) BETWEEN %s AND %s {where_tab} "
        "ORDER BY created_at DESC LIMIT 500",
        (start_date, end_date) + tab_params, fetch=True
    ) or []

    # ── Expenses list (P3) ────────────────────────────────────────────────────
    expenses_list = execute_query(
        "SELECT * FROM expenses WHERE expense_date BETWEEN %s AND %s "
        "ORDER BY expense_date DESC",
        (start_date, end_date), fetch=True
    ) or []
    expense_categories = execute_query(
        "SELECT DISTINCT category FROM expenses ORDER BY category", fetch=True
    ) or []

    # ── Mitra Summary ─────────────────────────────────────────────────────────
    mitra_summary = execute_query(
        "SELECT party_name, COUNT(*) as tx_count, "
        "COALESCE(SUM(gross_amount),0) as gross, "
        "COALESCE(SUM(cost_amount),0) as cost, "
        "COALESCE(SUM(net_profit),0) as net "
        "FROM income_ledger "
        "WHERE source_type='mitra_voucher' AND DATE(created_at) BETWEEN %s AND %s "
        "GROUP BY party_name ORDER BY gross DESC",
        (start_date, end_date), fetch=True
    ) or []

    pending_count = execute_query(
        "SELECT COUNT(*) as c FROM payments WHERE status='pending'", fetch_one=True
    )
    pending_count = int(pending_count['c']) if pending_count else 0

    return render_template(
        'reports/index.html',
        start_date=start_date, end_date=end_date, source_tab=source_tab,
        # totals
        gross_total=gross_total, cost_total=cost_total,
        net_total=net_total, expense_total=expense_total, real_profit=real_profit,
        breakdown=breakdown,
        # chart
        chart_labels=chart_labels, chart_values=chart_values,
        # list
        transactions=transactions, mitra_summary=mitra_summary,
        # piutang
        piutang_list=piutang_list, piutang_total=piutang_total,
        # monthly
        monthly_summary=monthly_summary,
        # expenses
        expenses_list=expenses_list, expense_categories=expense_categories,
        pending_count=pending_count,
    )


@reports_bp.route('/expense/add', methods=['POST'])
def expense_add():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    category    = request.form.get('category', 'Operasional').strip()
    description = request.form.get('description', '').strip()
    amount      = request.form.get('amount', '0')
    expense_date= request.form.get('expense_date') or datetime.date.today().strftime('%Y-%m-%d')

    if not description or float(amount) <= 0:
        flash('Deskripsi dan nominal harus diisi.', 'error')
        return redirect(url_for('reports.index', tab='expenses'))

    execute_query(
        "INSERT INTO expenses (category, description, amount, expense_date, recorded_by) "
        "VALUES (%s, %s, %s, %s, %s)",
        (category, description, float(amount), expense_date, session.get('username','admin'))
    )
    flash('Pengeluaran berhasil dicatat.', 'success')
    return redirect(url_for('reports.index', tab='expenses'))


@reports_bp.route('/expense/delete/<int:id>', methods=['POST'])
def expense_delete(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    execute_query("DELETE FROM expenses WHERE id=%s", (id,))
    flash('Pengeluaran dihapus.', 'success')
    return redirect(url_for('reports.index', tab='expenses'))


@reports_bp.route('/export')
def export():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    start_date = request.args.get('start_date', datetime.date.today().replace(day=1).strftime('%Y-%m-%d'))
    end_date   = request.args.get('end_date',   datetime.date.today().strftime('%Y-%m-%d'))
    source_tab = request.args.get('tab', 'all')

    where_tab  = "AND source_type=%s" if source_tab not in ('all','piutang','monthly','expenses') else ""
    tab_params = (source_tab,) if source_tab not in ('all','piutang','monthly','expenses') else ()

    rows = execute_query(
        "SELECT id, source_type, ref_number, description, gross_amount, cost_amount, net_profit, "
        "party_name, category, recorded_by, created_at "
        "FROM income_ledger "
        f"WHERE DATE(created_at) BETWEEN %s AND %s {where_tab} "
        "ORDER BY created_at DESC",
        (start_date, end_date) + tab_params, fetch=True
    ) or []

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID','Jenis','Ref/Kode','Keterangan','Pemasukan Bruto',
                     'HPP / Diskon','Net Profit','Pihak Terkait','Kategori','Dicatat Oleh','Waktu'])
    for r in rows:
        writer.writerow([r['id'], r['source_type'], r['ref_number'], r['description'],
                         r['gross_amount'], r['cost_amount'], r['net_profit'],
                         r['party_name'], r['category'], r['recorded_by'], str(r['created_at'])])

    output.seek(0)
    filename = f"laporan_keuangan_{start_date}_sd_{end_date}.csv"
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    return response
