from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from web.database import execute_query
from web.mikrotik_api import MikrotikApi
from web.decorators import admin_required
import socket

tools_bp = Blueprint('tools', __name__)

@tools_bp.route('/resolver', methods=['GET', 'POST'])
def resolver():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    domain = ""
    ips = []
    error = None

    if request.method == 'POST':
        domain = request.form.get('domain', '').strip()
        if domain:
            try:
                # Strip protocol if user pasted a URL
                if "://" in domain:
                    domain = domain.split("://")[1]
                domain = domain.split("/")[0]

                # Resolve all IP addresses for the domain
                _, _, ip_list = socket.gethostbyname_ex(domain)
                ips = list(set(ip_list)) # Remove duplicates
                
                if not ips:
                    error = "Tidak menemukan IP untuk domain tersebut."
            except socket.gaierror:
                error = "Gagal menghubungi DNS (Domain tidak valid atau koneksi internet bermasalah)."
            except Exception as e:
                error = f"Error: {str(e)}"
        else:
            error = "Domain tidak boleh kosong."

    # Using ip_address instead of vpn_ip for router connection, this needs to be dynamically handled or use standard router query
    routers = []
    try:
        routers = execute_query("SELECT id, name, ip_address FROM routers", fetch=True) or []
    except:
        routers = execute_query("SELECT id, name, vpn_ip as ip_address FROM routers", fetch=True) or []
    
    return render_template('tools/resolver.html', domain=domain, ips=ips, error=error, routers=routers)

@tools_bp.route('/push_address_list', methods=['POST'])
def push_address_list():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    try:
        data = request.get_json()
        router_id = data.get('router_id')
        list_name = data.get('list_name')
        ips = data.get('ips', [])

        if not router_id or not list_name or not ips:
            return jsonify({'success': False, 'message': 'Data tidak lengkap.'}), 400

        # Fetch router details
        router = execute_query("SELECT * FROM routers WHERE id=%s", (router_id,), fetch_one=True)
        if not router:
            return jsonify({'success': False, 'message': 'Router tidak ditemukan.'}), 404

        # Important to use the correct IP to connect
        connect_ip = router.get('vpn_ip') or router.get('ip_address')
        
        # MikrotikApi takes: host, port, timeout
        api = MikrotikApi(connect_ip, int(router.get('api_port') or 8728))
        if not api.connect():
            return jsonify({'success': False, 'message': 'Gagal koneksi ke router MikroTik.'}), 500

        if not api.login(router['api_user'], router['api_password']):
            return jsonify({'success': False, 'message': 'Gagal login ke router MikroTik. Cek user/pass API.'}), 500

        success_count = 0
        error_msgs = []
        
        import time
        # Send one by one, adding a tiny sleep every 100 IPs to let Mikrotik CPU breathe
        for i, ip in enumerate(ips):
            comment = f"Auto-added via MikroFun Catalog"
            status, msg = api.add_firewall_address_list(list_name, ip, comment)
            if status:
                success_count += 1
            else:
                # If message contains 'already have', we can still consider it a pass visually
                if 'already have' in msg.lower():
                    success_count += 1
                else:
                    error_msgs.append(f"{ip}: {msg}")
                    
            # Safe throttle for bulk
            if (i + 1) % 150 == 0:
                time.sleep(1) # 1 second pause per 150 IPs

        api.disconnect()

        if success_count == len(ips):
            return jsonify({'success': True, 'message': f'Berhasil memasukkan {success_count} IP ke Address List "{list_name}".'})
        elif success_count > 0:
            return jsonify({'success': True, 'message': f'Berhasil {success_count} IP, Gagal {len(ips)-success_count} IP. Error: {", ".join(error_msgs)}'})
        else:
            return jsonify({'success': False, 'message': f'Gagal memasukkan semua IP. Error: {", ".join(error_msgs)}'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# Preset Catalog URLs (Menggunakan repository aktif seperti Helmiau / MikrotikID)
CATALOG_URLS = {
    'speedtest_indo': 'https://raw.githubusercontent.com/helmiau/mikrotik-script/master/Address%20List/Speedtest.rsc',
    'mobile_legends': 'https://raw.githubusercontent.com/helmiau/mikrotik-script/master/Address%20List/Games/Mobile_Legends.rsc',
    'free_fire': 'https://raw.githubusercontent.com/helmiau/mikrotik-script/master/Address%20List/Games/Free_Fire.rsc',
    'whatsapp': 'https://raw.githubusercontent.com/helmiau/mikrotik-script/master/Address%20List/Sosmed/Whatsapp.rsc',
    'tiktok': 'https://raw.githubusercontent.com/helmiau/mikrotik-script/master/Address%20List/Sosmed/Tiktok.rsc',
    'zoom': 'https://raw.githubusercontent.com/helmiau/mikrotik-script/master/Address%20List/Web/Zoom_Meeting.rsc',
}




