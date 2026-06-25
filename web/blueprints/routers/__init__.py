"""Routers Blueprint - WireGuard VPN Management"""
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from web.database import execute_query
from web.vpn_helper import (generate_wireguard_keys, get_next_vpn_ip, add_wireguard_peer, 
                           remove_wireguard_peer, generate_mikrotik_script, generate_vpn_password,
                           add_ppp_secret, remove_ppp_secret, add_ipsec_secret, remove_ipsec_secret)
import requests

routers_bp = Blueprint('routers', __name__)

@routers_bp.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    routers = execute_query("SELECT * FROM routers ORDER BY created_at DESC", fetch=True) or []
    return render_template('routers/list.html', routers=routers)

@routers_bp.route('/refresh_status', methods=['POST'])
def refresh_status():
    """Check router connectivity via Mikrotik API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Not auth'}), 401
    try:
        from web.mikrotik_api import MikrotikApi
        
        routers = execute_query("SELECT * FROM routers", fetch=True) or []
        updated = 0
        
        for r in routers:
            try:
                api = MikrotikApi(r['vpn_ip'], r['api_port'])
                if api.login(r['api_user'], r['api_password']):
                    # Transition to Online logic could go here too, but mostly we care about Offline
                    if r.get('status') == 'offline':
                        from web.telegram_helper import send_telegram_message
                        send_telegram_message(f"🟢 *Router Kembali Online*\n\nRouter *{r['name']}* telah kembali terhubung ke sistem MikroFun.")

                    execute_query(
                        "UPDATE routers SET status='online', last_seen=NOW() WHERE id=%s",
                        (r['id'],)
                    )
                    api.close()
                    updated += 1
                else:
                    if r.get('status') != 'offline':
                        from web.telegram_helper import send_telegram_message
                        send_telegram_message(f"🔴 *ROUTER TERPUTUS!*\n\nRouter *{r['name']}* terputus dari jaringan! Cek Mikrotik atau koneksi VPN.")
                    execute_query(
                        "UPDATE routers SET status='offline' WHERE id=%s",
                        (r['id'],)
                    )
            except Exception as e:
                # Router unreachable
                if r.get('status') != 'offline':
                    from web.telegram_helper import send_telegram_message
                    send_telegram_message(f"🔴 *ROUTER TERPUTUS!*\n\nSistem kehilangan koneksi API ke Router *{r['name']}*.\n_Auto-Alert MikroFun_")
                execute_query(
                    "UPDATE routers SET status='offline' WHERE id=%s",
                    (r['id'],)
                )
        
        return jsonify({'success': True, 'updated': updated})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@routers_bp.route('/add', methods=['GET', 'POST'])
def add():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    if request.method == 'POST':
        name = request.form.get('name')
        api_user = request.form.get('api_user', '')
        api_password = request.form.get('api_password', '')
        api_port = request.form.get('api_port', 8728)
        vpn_type = request.form.get('vpn_type', 'wireguard')
        target_ip_form = request.form.get('target_ip') # New field from UI
        
        # Determine VPN IP
        if vpn_type in ['direct_local', 'public_ip', 'zerotier']:
            if not target_ip_form:
                flash('IP Target wajib diisi untuk mode ini!', 'error')
                return redirect(url_for('routers.add'))
            vpn_ip = target_ip_form
        else:
            vpn_ip = get_next_vpn_ip()
            if not vpn_ip:
                flash('Tidak ada IP VPN yang tersedia!', 'error')
                return redirect(url_for('routers.add'))
            
        priv_key, pub_key, vpn_password_str = None, None, None
        
        if vpn_type == 'wireguard':
            priv_key, pub_key = generate_wireguard_keys()
            if not priv_key:
                flash('Gagal generate WireGuard keys!', 'error')
                return redirect(url_for('routers.add'))
        elif vpn_type in ['l2tp', 'sstp']:
            vpn_password_str = generate_vpn_password()
            
        router_id = execute_query(
            "INSERT INTO routers (name, vpn_ip, vpn_public_key, vpn_private_key, vpn_type, vpn_password, api_user, api_password, api_port, status) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'offline')",
            (name, vpn_ip, pub_key, priv_key, vpn_type, vpn_password_str, api_user, api_password, api_port)
        )
        
        if router_id:
            # Add to respective VPN config
            if vpn_type == 'wireguard':
                add_wireguard_peer(name, vpn_ip, pub_key)
            elif vpn_type in ['l2tp', 'sstp']:
                add_ppp_secret(name, vpn_password_str, vpn_ip)
                if vpn_type == 'l2tp':
                    add_ipsec_secret(name, vpn_password_str)
                
            # Detect IP for VPN endpoint / RADIUS address
            import socket
            if vpn_type in ('direct_local', 'public_ip'):
                # Local/direct mode — use LAN IP, not public ISP IP
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.settimeout(1)
                    s.connect(('8.8.8.8', 1))
                    accessible_ip = s.getsockname()[0]
                    s.close()
                except:
                    accessible_ip = request.host.split(':')[0]
            else:
                # VPN modes — use public IP for remote MikroTik endpoint
                try:
                    accessible_ip = requests.get('https://api.ipify.org', timeout=3).text.strip()
                except:
                    accessible_ip = request.host.split(':')[0]
                    if accessible_ip in ['127.0.0.1', 'localhost']:
                        try:
                            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            s.settimeout(1)
                            s.connect(('8.8.8.8', 1))
                            accessible_ip = s.getsockname()[0]
                            s.close()
                        except:
                            accessible_ip = "YOUR_SERVER_IP"
                
            script = generate_mikrotik_script(name, vpn_ip, priv_key, accessible_ip, vpn_type, vpn_password_str)
            session['mikrotik_script'] = script
            session['router_name'] = name
            flash(f'Router {name} berhasil ditambahkan!', 'success')
            return redirect(url_for('routers.show_script'))
        flash('Gagal menambahkan router!', 'error')
    return render_template('routers/add.html')

@routers_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    router = execute_query("SELECT * FROM routers WHERE id=%s", (id,), fetch_one=True)
    if not router:
        flash('Router tidak ditemukan!', 'error')
        return redirect(url_for('routers.index'))

    if request.method == 'POST':
        name = request.form.get('name')
        api_user = request.form.get('api_user', '')
        api_password = request.form.get('api_password', '')
        api_port_str = request.form.get('api_port', '8728')
        
        try:
            api_port = int(api_port_str) if api_port_str.isdigit() else 8728
        except:
            api_port = 8728

        # Conditional Update: Only update password if provided
        if api_password:
            execute_query(
                "UPDATE routers SET name=%s, api_user=%s, api_password=%s, api_port=%s WHERE id=%s",
                (name, api_user, api_password, api_port, id)
            )
        else:
            execute_query(
                "UPDATE routers SET name=%s, api_user=%s, api_port=%s WHERE id=%s",
                (name, api_user, api_port, id)
            )
            
        flash('Router berhasil diupdate!', 'success')
        return redirect(url_for('routers.index'))
        
    return render_template('routers/edit.html', router=router)

@routers_bp.route('/show_script')
def show_script():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    script = session.pop('mikrotik_script', None)
    router_name = session.pop('router_name', 'Router')
    if not script:
        return redirect(url_for('routers.index'))
    return render_template('routers/script.html', script=script, router_name=router_name)

@routers_bp.route('/api/get_script/<int:id>')
def get_script(id):
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    router = execute_query("SELECT * FROM routers WHERE id=%s", (id,), fetch_one=True)
    if not router:
        return jsonify({'error': 'Router not found'}), 404
        
    # Detect Real Public IP
    try:
        accessible_ip = requests.get('https://api.ipify.org', timeout=3).text.strip()
    except:
        accessible_ip = request.host.split(':')[0]
        if accessible_ip in ['127.0.0.1', 'localhost']:
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(1)
                s.connect(('8.8.8.8', 1))
                accessible_ip = s.getsockname()[0]
                s.close()
            except:
                accessible_ip = "YOUR_SERVER_IP"
        
    script = generate_mikrotik_script(
        router['name'], 
        router['vpn_ip'], 
        router['vpn_private_key'], 
        accessible_ip,
        router.get('vpn_type', 'wireguard'),
        router.get('vpn_password', None)
    )
    
    return jsonify({'success': True, 'script': script, 'router_name': router['name']})

@routers_bp.route('/delete/<int:id>')
def delete(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    router = execute_query("SELECT * FROM routers WHERE id=%s", (id,), fetch_one=True)
    if router:
        vpn_type = router.get('vpn_type', 'wireguard')
        if vpn_type == 'wireguard':
            remove_wireguard_peer(router['vpn_public_key'])
        elif vpn_type in ['l2tp', 'sstp']:
            remove_ppp_secret(router['name'])
            if vpn_type == 'l2tp':
                remove_ipsec_secret(router['name'])
            
        execute_query("DELETE FROM routers WHERE id=%s", (id,))
        flash('Router berhasil dihapus!', 'success')
    return redirect(url_for('routers.index'))

@routers_bp.route('/api/pools/<int:router_id>')
def api_get_pools(router_id):
    """Fetch IP Pools from MikroTik router via API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    router = execute_query("SELECT * FROM routers WHERE id=%s", (router_id,), fetch_one=True)
    if not router:
        return jsonify({'error': 'Router not found'}), 404
    
    try:
        from web.mikrotik_api import MikrotikApi
        target_ip = router.get('vpn_ip') or router.get('ip_address', '')
        if not target_ip:
            return jsonify({'error': 'Router has no IP/VPN IP configured'}), 400
        
        api = MikrotikApi(target_ip, int(router.get('api_port', 8728)), timeout=5)
        if not api.login(router.get('api_user', 'admin'), router.get('api_password', '')):
            return jsonify({'error': 'API login failed — check credentials'}), 400
        
        # Fetch IP Pools
        pools = api.query(['/ip/pool/print', '=.proplist=name'])
        api.close()
        
        if pools is None:
            return jsonify({'error': 'Failed to fetch pools (API trap)'}), 500
        
        pool_names = [p.get('name', '') for p in pools if p.get('name')]
        return jsonify({'success': True, 'pools': pool_names})
    
    except Exception as e:
        return jsonify({'error': f'Connection failed: {str(e)}'}), 500
