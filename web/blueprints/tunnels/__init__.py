"""MikroTunnel Blueprint - VPN NAT Traversal Remote Access"""
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from web.database import execute_query
from web.tunnel_helper import (
    get_next_tunnel_ip, get_available_ports, generate_tunnel_password,
    generate_tunnel_username, setup_tunnel_nat, teardown_tunnel_nat,
    save_iptables, add_tunnel_l2tp_secret, remove_tunnel_l2tp_secret,
    check_tunnel_alive, get_server_public_ip, generate_mikrotik_tunnel_script
)

from web.decorators import admin_required

tunnels_bp = Blueprint('tunnels', __name__)

@tunnels_bp.route('/')
@admin_required
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    tunnels = execute_query(
        "SELECT * FROM tunnels ORDER BY created_at DESC",
        fetch=True
    ) or []
    
    server_ip = get_server_public_ip()
    
    return render_template('tunnels/list.html', tunnels=tunnels, server_ip=server_ip)


@tunnels_bp.route('/create', methods=['POST'])
@admin_required
def create():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    tunnel_name = request.form.get('tunnel_name', '').strip()
    mk_user = request.form.get('mikrotik_user', 'admin').strip()
    mk_pass = request.form.get('mikrotik_password', '').strip()
    mk_winbox_port = request.form.get('mikrotik_winbox_port', '8291').strip()
    mk_web_port = request.form.get('mikrotik_web_port', '80').strip()
    mk_api_port = request.form.get('mikrotik_api_port', '8728').strip()
    
    if not tunnel_name:
        flash('Nama tunnel wajib diisi!', 'error')
        return redirect(url_for('tunnels.index'))
    
    try:
        mk_winbox_port = int(mk_winbox_port)
        mk_web_port = int(mk_web_port)
        mk_api_port = int(mk_api_port)
    except ValueError:
        flash('Port harus berupa angka!', 'error')
        return redirect(url_for('tunnels.index'))
    
    # Allocate resources
    internal_ip = get_next_tunnel_ip()
    if not internal_ip:
        flash('Tidak ada IP tunnel tersedia!', 'error')
        return redirect(url_for('tunnels.index'))
    
    winbox_port, web_port, api_port = get_available_ports()
    if not winbox_port:
        flash('Tidak ada port publik tersedia!', 'error')
        return redirect(url_for('tunnels.index'))
    
    username = generate_tunnel_username(tunnel_name)
    password = generate_tunnel_password()
    
    # 1. Add L2TP secret
    add_tunnel_l2tp_secret(username, password, internal_ip)
    
    # 2. Setup iptables NAT with custom MikroTik ports
    setup_tunnel_nat(internal_ip, winbox_port, web_port, api_port, mk_winbox_port, mk_web_port, mk_api_port)
    save_iptables()
    
    # 3. Save to database
    execute_query(
        "INSERT INTO tunnels (tunnel_name, vpn_username, vpn_password, internal_ip, "
        "mikrotik_user, mikrotik_password, mikrotik_winbox_port, mikrotik_web_port, mikrotik_api_port, "
        "public_winbox_port, public_web_port, public_api_port, is_active) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)",
        (tunnel_name, username, password, internal_ip, mk_user, mk_pass,
         mk_winbox_port, mk_web_port, mk_api_port, winbox_port, web_port, api_port)
    )
    
    flash(f'Tunnel "{tunnel_name}" berhasil dibuat! Winbox: {winbox_port}, Web: {web_port}', 'success')
    return redirect(url_for('tunnels.index'))


@tunnels_bp.route('/toggle/<int:id>', methods=['POST'])
@admin_required
def toggle(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    tunnel = execute_query("SELECT * FROM tunnels WHERE id=%s", (id,), fetch_one=True)
    if not tunnel:
        flash('Tunnel tidak ditemukan!', 'error')
        return redirect(url_for('tunnels.index'))
    
    mk_wb = tunnel.get('mikrotik_winbox_port') or 8291
    mk_web = tunnel.get('mikrotik_web_port') or 80
    mk_api = tunnel.get('mikrotik_api_port') or 8728
    
    if tunnel['is_active']:
        teardown_tunnel_nat(tunnel['internal_ip'], tunnel['public_winbox_port'], tunnel['public_web_port'], tunnel['public_api_port'], mk_wb, mk_web, mk_api)
        execute_query("UPDATE tunnels SET is_active=FALSE WHERE id=%s", (id,))
        flash('Tunnel dinonaktifkan.', 'info')
    else:
        setup_tunnel_nat(tunnel['internal_ip'], tunnel['public_winbox_port'], tunnel['public_web_port'], tunnel['public_api_port'], mk_wb, mk_web, mk_api)
        execute_query("UPDATE tunnels SET is_active=TRUE WHERE id=%s", (id,))
        flash('Tunnel diaktifkan kembali.', 'success')
    
    save_iptables()
    return redirect(url_for('tunnels.index'))


@tunnels_bp.route('/delete/<int:id>', methods=['POST'])
@admin_required
def delete(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    tunnel = execute_query("SELECT * FROM tunnels WHERE id=%s", (id,), fetch_one=True)
    if not tunnel:
        flash('Tunnel tidak ditemukan!', 'error')
        return redirect(url_for('tunnels.index'))
    
    mk_wb = tunnel.get('mikrotik_winbox_port') or 8291
    mk_web = tunnel.get('mikrotik_web_port') or 80
    mk_api = tunnel.get('mikrotik_api_port') or 8728
    
    # 1. Remove iptables NAT
    teardown_tunnel_nat(tunnel['internal_ip'], tunnel['public_winbox_port'], tunnel['public_web_port'], tunnel['public_api_port'], mk_wb, mk_web, mk_api)
    save_iptables()
    
    # 2. Remove L2TP secret
    remove_tunnel_l2tp_secret(tunnel['vpn_username'])
    
    # 3. Delete from database
    execute_query("DELETE FROM tunnels WHERE id=%s", (id,))
    
    flash('Tunnel berhasil dihapus.', 'success')
    return redirect(url_for('tunnels.index'))


@tunnels_bp.route('/script/<int:id>')
@admin_required
def script(id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    tunnel = execute_query("SELECT * FROM tunnels WHERE id=%s", (id,), fetch_one=True)
    if not tunnel:
        flash('Tunnel tidak ditemukan!', 'error')
        return redirect(url_for('tunnels.index'))
    
    server_ip = get_server_public_ip()
    script_text = generate_mikrotik_tunnel_script(
        server_ip, tunnel['vpn_username'], tunnel['vpn_password']
    )
    script_text = script_text.replace('<PORT_WINBOX>', str(tunnel['public_winbox_port']))
    script_text = script_text.replace('<PORT_WEB>', str(tunnel['public_web_port']))
    script_text = script_text.replace('<PORT_API>', str(tunnel['public_api_port']))
    
    return render_template('tunnels/script.html',
                           tunnel=tunnel, script=script_text, server_ip=server_ip)


@tunnels_bp.route('/status')
def status():
    """AJAX endpoint: check connectivity of all active tunnels."""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    tunnels = execute_query(
        "SELECT id, internal_ip FROM tunnels WHERE is_active=TRUE",
        fetch=True
    ) or []
    
    results = {}
    for t in tunnels:
        results[t['id']] = check_tunnel_alive(t['internal_ip'])
    
    return jsonify({'success': True, 'status': results})
