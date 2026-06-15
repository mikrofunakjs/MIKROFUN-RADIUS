"""Customers Blueprint - PPPoE User Management"""
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from web.database import execute_query
from web.decorators import cs_or_admin_required
import datetime

customers_bp = Blueprint('customers', __name__)

@customers_bp.route('/', methods=['GET'])
@cs_or_admin_required
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    q = request.args.get('q', '')
    query = (
        "SELECT c.*, p.name as profile_name, r.name as router_name, "
        "(SELECT COUNT(*) FROM active_sessions s WHERE s.username = c.username) as active_session_count, "
        "(SELECT COALESCE(SUM(acctinputoctets),0) FROM radacct ra WHERE ra.username = c.username) as total_upload, "
        "(SELECT COALESCE(SUM(acctoutputoctets),0) FROM radacct ra WHERE ra.username = c.username) as total_download "
        "FROM customers c "
        "LEFT JOIN profiles p ON c.profile_id = p.id "
        "LEFT JOIN routers r ON c.router_id = r.id "
        "WHERE (c.mac_address IS NULL OR c.mac_address = '') "
    )
    params = ()
    
    if q:
        query += " AND (c.name LIKE %s OR c.username LIKE %s)"
        params = (f"%{q}%", f"%{q}%")
        
    query += " ORDER BY c.created_at DESC"
    
    customers = execute_query(query, params, fetch=True)
    
    total_customers = execute_query("SELECT COUNT(*) as c FROM customers WHERE mac_address IS NULL OR mac_address = ''", fetch_one=True)['c']
    
    return render_template('customers/list.html', customers=customers or [], total_customers=total_customers)

@customers_bp.route('/bulk_action', methods=['POST'])
def bulk_action():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    action = request.form.get('action')
    customer_ids = request.form.getlist('customer_ids')
    
    if not customer_ids:
        flash('Tidak ada customer yang dipilih!', 'warning')
        return redirect(url_for('customers.index'))
        
    success_count = 0

    if action == 'check_status':
        # Optimized Bulk Check: Group by Router
        format_strings = ','.join(['%s'] * len(customer_ids))
        query = (
             f"SELECT c.username, r.id as router_id, r.vpn_ip, r.api_user, r.api_password, r.api_port "
             f"FROM customers c LEFT JOIN routers r ON c.router_id = r.id "
             f"WHERE c.id IN ({format_strings})"
        )
        customers_to_check = execute_query(query, tuple(customer_ids), fetch=True)
        
        if customers_to_check:
            from web.mikrotik_api import MikrotikApi
            
            # Group by Router
            router_groups = {}
            for c in customers_to_check:
                 if not c['router_id']: continue 
                 if c['router_id'] not in router_groups:
                     router_groups[c['router_id']] = {'creds': c, 'users': []}
                 router_groups[c['router_id']]['users'].append(c['username'])
            
            # Process Each Router
            for rid, group in router_groups.items():
                 creds = group['creds']
                 target_users = set(group['users'])
                 
                 try:
                     api = MikrotikApi(creds['vpn_ip'], creds.get('api_port', 8728))
                     if api.connect() and api.login(creds['api_user'], creds['api_password']):
                         # Fetch ALL active users once
                         active_rows = api.query(['/ppp/active/print'])
                         api.close()
                         
                         active_map = {row.get('name'): row for row in active_rows if row.get('name')}
                         
                         for user in target_users:
                             if user in active_map:
                                 # ONLINE
                                 pkt = active_map[user]
                                 nas_ip = creds['vpn_ip']
                                 session_id = pkt.get('.id', 'unknown')
                                 execute_query(
                                     "INSERT INTO active_sessions (username, nas_ip, acct_session_id) VALUES (%s, %s, %s) "
                                     "ON DUPLICATE KEY UPDATE updated_at=NOW()",
                                     (user, nas_ip, session_id)
                                 )
                             else:
                                 # OFFLINE
                                 execute_query("DELETE FROM active_sessions WHERE username=%s", (user,))
                         
                         success_count += len(target_users)
                 except Exception as e:
                     print(f"Bulk Check Error {creds['vpn_ip']}: {e}")

    else:
        # Standard Item-by-Item Loop
        for cid in customer_ids:
            try:
                if action == 'delete':
                    # Get info for API kick
                    customer = execute_query(
                        "SELECT c.username, r.vpn_ip, r.api_user, r.api_password, r.api_port "
                        "FROM customers c LEFT JOIN routers r ON c.router_id = r.id WHERE c.id=%s", 
                        (cid,), fetch_one=True
                    )
                    if customer and customer['api_user']:
                        try_api_disconnect(customer, customer['username'])
                    
                    execute_query("DELETE FROM customers WHERE id=%s", (cid,))
                    
                elif action == 'isolir':
                    customer = execute_query(
                        "SELECT c.username, r.vpn_ip, r.api_user, r.api_password, r.api_port "
                        "FROM customers c LEFT JOIN routers r ON c.router_id = r.id WHERE c.id=%s", 
                        (cid,), fetch_one=True
                    )
                    if customer and customer['api_user']:
                        try_api_disconnect(customer, customer['username'])
                    
                    # Force remove session
                    execute_query("DELETE FROM active_sessions WHERE username=%s", (customer['username'],))
                        
                    execute_query("UPDATE customers SET status='isolir' WHERE id=%s", (cid,))
                    
                elif action == 'activate':
                    execute_query("UPDATE customers SET status='active' WHERE id=%s", (cid,))
                    
                success_count += 1
            except Exception as e:
                continue
            
    flash(f'Berhasil memproses {success_count} customer.', 'success')
    return redirect(url_for('customers.index'))

@customers_bp.route('/add', methods=['GET', 'POST'])
@cs_or_admin_required
def add():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    if request.method == 'POST':
        name = request.form.get('name')
        username = request.form.get('username')
        password = request.form.get('password')
        service_type = request.form.get('service_type', 'pppoe')
        profile_id = request.form.get('profile_id')
        router_id = request.form.get('router_id')
        phone = request.form.get('phone', '')
        address = request.form.get('address', '')
        due_date = request.form.get('due_date') or None

        odp_id = request.form.get('odp_id') or None
        port_number = request.form.get('port_number') or None
        coordinates = request.form.get('coordinates', '')
        
        mac_address = request.form.get('mac_address', '').strip().upper() or None
        static_ip = request.form.get('static_ip', '').strip() or None

        # CHECK LIMIT FOR FREE USERS
        from web.license_service import is_premium
        if not is_premium():
             current_count = execute_query("SELECT COUNT(*) as c FROM customers", fetch_one=True)['c']
             if current_count >= 50:
                 flash('Free Version limited to 50 customers. Please upgrade to Premium.', 'error')
                 return redirect(url_for('customers.add'))

        result = execute_query(
            "INSERT INTO customers (name, username, password, service_type, profile_id, router_id, phone, address, due_date, status, odp_id, port_number, coordinates, mac_address, static_ip) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s,%s)",
            (name, username, password, service_type, profile_id, router_id, phone, address, due_date, odp_id, port_number, coordinates, mac_address, static_ip)
        )
        if result:
            from web.blueprints.notifications import add_notification
            add_notification(
                title="Customer Created",
                message=f"Created customer {name} ({username})",
                category="success"
            )
            flash('Customer berhasil dibuat', 'success')
        else:
            flash('Gagal membuat customer', 'error')
            
        return redirect(url_for('customers.index'))
        
    routers = execute_query("SELECT * FROM routers ORDER BY name", fetch=True) or []
    profiles = execute_query("SELECT * FROM profiles WHERE type=%s ORDER BY name", ('pppoe',), fetch=True) or []
    odps = execute_query("SELECT * FROM odps ORDER BY name", fetch=True) or []
    
    return render_template('customers/add.html', routers=routers, profiles=profiles, odps=odps)

@customers_bp.route('/check_status/<int:id>')
def check_status(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    customer = execute_query(
        "SELECT c.username, r.vpn_ip, r.api_user, r.api_password, r.api_port "
        "FROM customers c LEFT JOIN routers r ON c.router_id = r.id WHERE c.id=%s", 
        (id,), fetch_one=True
    )
    
    if not customer:
        flash('Customer tidak ditemukan', 'error')
        return redirect(url_for('customers.index'))
        
    username = customer['username']
    
    # Logic: Connect -> Check. If fail connect/check -> Offline
    try:
        from web.mikrotik_api import MikrotikApi
        
        api = MikrotikApi(customer['vpn_ip'], customer.get('api_port', 8728))
        if api.connect():
             if api.login(customer['api_user'], customer['api_password']):
                 user_data = api.get_active_user(username)
                 api.close()
                 
                 if user_data:
                     # ONLINE
                     nas_ip = customer['vpn_ip']
                     session_id = user_data.get('.id', 'unknown')
                     execute_query(
                         "INSERT INTO active_sessions (username, nas_ip, acct_session_id) VALUES (%s, %s, %s) "
                         "ON DUPLICATE KEY UPDATE updated_at=NOW()",
                         (username, nas_ip, session_id)
                     )
                     flash(f'User {username} is ONLINE', 'success')
                 else:
                     # OFFLINE (User not found in active list)
                     execute_query("DELETE FROM active_sessions WHERE username=%s", (username,))
                     flash(f'User {username} is OFFLINE', 'warning')
             else:
                 api.close()
                 flash('Gagal login ke Mikrotik', 'error')
        else:
             # Connect Fail -> Assume Offline
             execute_query("DELETE FROM active_sessions WHERE username=%s", (username,))
             flash(f'Gagal koneksi ke Mikrotik ({customer["vpn_ip"]}). Status set OFFLINE.', 'error')
             
    except Exception as e:
        flash(f'Error Check Status: {e}', 'error')
        
    return redirect(url_for('customers.index'))

@customers_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@cs_or_admin_required
def edit(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    customer = execute_query("SELECT * FROM customers WHERE id=%s", (id,), fetch_one=True)
    if not customer:
        flash('Customer tidak ditemukan!', 'error')
        return redirect(url_for('customers.index'))

    if request.method == 'POST':
        due_date = request.form.get('due_date') or None
        mac_address = request.form.get('mac_address', '').strip().upper() or None
        static_ip = request.form.get('static_ip', '').strip() or None
        
        execute_query(
            "UPDATE customers SET name=%s, password=%s, profile_id=%s, router_id=%s, "
            "phone=%s, address=%s, due_date=%s, odp_id=%s, port_number=%s, coordinates=%s, mac_address=%s, static_ip=%s WHERE id=%s",
            (request.form.get('name'), request.form.get('password'),
             request.form.get('profile_id'), request.form.get('router_id'),
             request.form.get('phone',''), request.form.get('address',''), due_date,
             request.form.get('odp_id') or None, request.form.get('port_number') or None, 
             request.form.get('coordinates',''), mac_address, static_ip, id)
        )
        flash('Customer berhasil diupdate!', 'success')
        return redirect(url_for('customers.index'))

    profiles = execute_query("SELECT * FROM profiles ORDER BY name", fetch=True) or []
    routers = execute_query("SELECT * FROM routers ORDER BY name", fetch=True) or []
    odps = execute_query("SELECT * FROM odps ORDER BY name", fetch=True) or []
    return render_template('customers/edit.html', customer=customer, profiles=profiles, routers=routers, odps=odps)

def try_api_disconnect(router_data, username):
    """Helper to disconnect user via Mikrotik API"""
    if not router_data or not router_data.get('vpn_ip') or not router_data.get('api_user'):
        return False, "Router API not configured"
        
    try:
        from web.mikrotik_api import MikrotikApi
        api = MikrotikApi(router_data['vpn_ip'], int(router_data.get('api_port') or 8728))
        
        if not api.login(router_data['api_user'], router_data['api_password']):
            return False, "API Login Failed"
            
        success, msg = api.kick_user(username)
        api.close()
        return success, msg
    except Exception as e:
        return False, str(e)

@customers_bp.route('/delete/<int:id>')
def delete(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    # Get user info and router info BEFORE deleting
    customer = execute_query(
        "SELECT c.username, r.vpn_ip, r.api_user, r.api_password, r.api_port "
        "FROM customers c "
        "LEFT JOIN routers r ON c.router_id = r.id "
        "WHERE c.id=%s", 
        (id,), fetch_one=True
    )
    
    msg = 'Customer berhasil dihapus!'
    
    # 1. API Kick
    if customer and customer['api_user']:
        success, reason = try_api_disconnect(customer, customer['username'])
        if success:
            msg += ' Session diputus (API).'
        else:
            msg += f' (API Kick Warning: {reason})'
    
    # Force remove session
    execute_query("DELETE FROM active_sessions WHERE username=%s", (customer['username'],))

    # 2. Delete from DB
    execute_query("DELETE FROM customers WHERE id=%s", (id,))
    
    flash(msg, 'success')
    return redirect(url_for('customers.index'))

@customers_bp.route('/isolir/<int:id>')
def isolir(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    # Get user info
    customer = execute_query(
        "SELECT c.username, r.vpn_ip, r.api_user, r.api_password, r.api_port "
        "FROM customers c "
        "LEFT JOIN routers r ON c.router_id = r.id "
        "WHERE c.id=%s", 
        (id,), fetch_one=True
    )
    
    # 1. Update status in DB
    execute_query("UPDATE customers SET status='isolir' WHERE id=%s", (id,))
    
    msg = 'Customer diisolir!'
    
    # 2. API Kick
    if customer and customer['api_user']:
        success, reason = try_api_disconnect(customer, customer['username'])
        if success:
            msg += ' Session diputus (API).'
        else:
            msg += f' (API Kick Warning: {reason})'
    else:
        msg += ' (Note: API belum disetting di router, user tidak otomatis DC)'
            
    # 3. Force Remove Session from DB (UI Feedback)
    execute_query("DELETE FROM active_sessions WHERE username=%s", (customer['username'],))

    flash(msg, 'success')
    return redirect(url_for('customers.index'))

@customers_bp.route('/activate/<int:id>')
def activate(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    execute_query("UPDATE customers SET status='active' WHERE id=%s", (id,))
    flash('Customer diaktifkan!', 'success')
    return redirect(url_for('customers.index'))
