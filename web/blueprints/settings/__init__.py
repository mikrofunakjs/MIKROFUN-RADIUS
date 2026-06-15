from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
import subprocess
import re
import os
from web.database import execute_query

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/', methods=['GET', 'POST'])
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    if request.method == 'POST':
        radius_secret = request.form.get('radius_secret')
        
        if radius_secret:
            execute_query(
                "INSERT INTO settings (setting_key, setting_value) VALUES ('radius_secret', %s) "
                "ON DUPLICATE KEY UPDATE setting_value=%s",
                (radius_secret, radius_secret)
            )
        # Check license status
        from web.license_service import is_premium
        is_pro = is_premium()

        # Handle Logo Upload
        logo_file = request.files.get('company_logo')
        if logo_file and logo_file.filename:
            from werkzeug.utils import secure_filename
            filename = secure_filename(f"logo_{logo_file.filename}")
            upload_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'static', 'uploads', filename)
            
            # Ensure static/uploads exists (Double Check)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            
            logo_file.save(upload_path)
            logo_url = f"/static/uploads/{filename}"
            
            execute_query(
                "INSERT INTO settings (setting_key, setting_value) VALUES ('company_logo', %s) "
                "ON DUPLICATE KEY UPDATE setting_value=%s",
                (logo_url, logo_url)
            )

        # Company Profile Settings
        company_fields = ['company_name', 'company_address', 'company_phone', 'company_email']
        
        for field in company_fields:
            val = request.form.get(field)
            if val is not None:
                # Hanya company_name yang dikunci untuk Free Mode
                if not is_pro and field == 'company_name':
                    flash('Upgrade ke Premium untuk mengubah Nama ISP.', 'error')
                    continue
                
                execute_query(
                    "INSERT INTO settings (setting_key, setting_value) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE setting_value=%s",
                    (field, val, val)
                )
            
        flash('Settings updated successfully.', 'success')
        return redirect(url_for('settings.index'))
            
    # Load current settings
    settings_rows = execute_query("SELECT * FROM settings", fetch=True) or []
    settings_dict = {row['setting_key']: row['setting_value'] for row in settings_rows}
    
    return render_template('settings/index.html', settings=settings_dict)

@settings_bp.route('/activate-license', methods=['POST'])
def activate_license():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    license_key = request.form.get('license_key')
    
    # 1. Online Activation
    from web.license_service import activate_license_online
    success, msg = activate_license_online(license_key)
    
    if success:
        flash(f'Aktivasi Berhasil: {msg}', 'success')
    else:
        flash(f'Aktivasi Gagal: {msg}', 'error')
        
    return redirect(url_for('settings.index'))

@settings_bp.route('/deactivate-license')
def deactivate_license():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    from web.license_service import remove_license_from_db
    remove_license_from_db()
    import web.license_service as ls
    ls._premium_cache['status'] = False
    ls._premium_cache['last_checked'] = 0
    flash('Lisensi dinonaktifkan.', 'success')
    return redirect(url_for('settings.index'))

def get_setting(key, default=None):
    """Helper to get setting from DB"""
    try:
        from database import get_db
        conn = get_db()
        if not conn: return default
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT setting_value FROM settings WHERE setting_key=%s", (key,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row['setting_value'] if row else default
    except:
        return default

@settings_bp.route('/update-admin', methods=['POST'])
def update_admin():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    username = request.form.get('username')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    
    if not username:
        flash('Username tidak boleh kosong.', 'error')
        return redirect(url_for('settings.index'))
        
    updates = ["username=%s"]
    params = [username]
    
    if password:
        if password != confirm_password:
            flash('Password konfirmasi tidak cocok.', 'error')
            return redirect(url_for('settings.index'))
        updates.append("password=%s")
        params.append(password)
        
    # Update Admin (Assuming ID 1 or current logged in user if we tracked ID)
    # Since we only have one admin essentially in this simple version, let's update ID 1 or WHERE role='admin'
    # Better: Update based on current session username before change?
    # For simplicity in this project context: Update ID 1 (Default Admin)
    
    try:
        sql = f"UPDATE users SET {', '.join(updates)} WHERE id=1" # Assumes Default Admin is ID 1
        execute_query(sql, tuple(params))
        
        # Update Session
        session['username'] = username
        flash('Profil Admin berhasil diperbarui.', 'success')
    except Exception as e:
        flash(f'Gagal memperbarui profil: {e}', 'error')
        
    return redirect(url_for('settings.index'))

@settings_bp.route('/backup')
def backup():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    from web.backup_helper import backup_database
    sql_content, error = backup_database()
    
    if error:
        flash(f'Backup Gagal: {error}', 'error')
        return redirect(url_for('settings.index'))
        
    # Create Response
    from flask import Response
    import datetime
    
    filename = f"mikrofun_backup_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.sql"
    
    return Response(
        sql_content,
        mimetype="application/x-sql",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )

@settings_bp.route('/restore', methods=['POST'])
def restore():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    file = request.files.get('backup_file')
    if not file:
        flash('Tidak ada file yang dipilih.', 'error')
        return redirect(url_for('settings.index'))
        
    try:
        sql_content = file.read()
        from web.backup_helper import restore_database
        success, msg = restore_database(sql_content)
        
        if success:
            # Clear session to force re-login (safe side)
            session.clear()
            flash(f'Restore Berhasil! Silakan login kembali. ({msg})', 'success')
            return redirect(url_for('auth.login'))
        else:
            flash(f'Restore Gagal: {msg}', 'error')
            return redirect(url_for('settings.index'))
            
    except Exception as e:
        flash(f'Error reading file: {e}', 'error')
        return redirect(url_for('settings.index'))

@settings_bp.route('/backup-telegram', methods=['POST'])
def backup_telegram():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    from web.backup_helper import backup_database
    
    # Generate the backup and send it to telegram internally
    try:
        _, error = backup_database(send_to_telegram=True)
        
        if error:
            return jsonify({'success': False, 'message': error})
            
        return jsonify({'success': True, 'message': 'Backup berhasil dikirim ke Telegram'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

def check_zt_binary():
    """Check if zerotier-cli is available in common paths"""
    paths = ['zerotier-cli', '/usr/sbin/zerotier-cli', '/usr/bin/zerotier-cli']
    for p in paths:
        try:
            # Check if command exists without executing fully
            subprocess.run([p, "-v"], capture_output=True, text=True, timeout=2)
            return p
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None

@settings_bp.route('/zerotier/join', methods=['POST'])
def zerotier_join():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    network_id = request.form.get('network_id')
    if not network_id or len(network_id) != 16:
        return jsonify({'success': False, 'message': 'Network ID tidak valid (harus 16 karakter)'})
    
    zt_bin = check_zt_binary()
    if not zt_bin:
        return jsonify({
            'success': False, 
            'message': 'Gagal: Perintah "zerotier-cli" tidak ditemukan. Silakan jalankan kembali "sudo bash install.sh" di server Bos untuk menginstall ZeroTier.'
        })

    try:
        # 1. Save Network ID to DB
        execute_query(
            "INSERT INTO settings (setting_key, setting_value) VALUES ('zt_network_id', %s) "
            "ON DUPLICATE KEY UPDATE setting_value=%s",
            (network_id, network_id)
        )
        
        # 2. Join Network via CLI
        cmd = f"sudo {zt_bin} join {network_id}"
        process = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if process.returncode != 0:
            error_msg = process.stderr or process.stdout
            return jsonify({'success': False, 'message': f'Gagal join: {error_msg}'})
        
        return jsonify({'success': True, 'message': f'Berhasil mengirim permintaan join ke {network_id}'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@settings_bp.route('/zerotier/leave', methods=['POST'])
def zerotier_leave():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        network_id = get_setting('zt_network_id')
        if not network_id:
            return jsonify({'success': False, 'message': 'Network ID tidak ditemukan'})
            
        zt_bin = check_zt_binary()
        if not zt_bin:
            return jsonify({'success': False, 'message': 'Gagal: Perintah zerotier-cli tidak ditemukan.'})

        cmd = f"sudo {zt_bin} leave {network_id}"
        subprocess.run(cmd, shell=True)
        
        # Clear IP from settings
        execute_query("DELETE FROM settings WHERE setting_key = 'zt_vps_ip'")
        
        return jsonify({'success': True, 'message': 'Berhasil keluar dari jaringan ZeroTier'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@settings_bp.route('/zerotier/status')
def zerotier_status():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    network_id = get_setting('zt_network_id')
    if not network_id:
        return jsonify({'status': 'none'})
        
    zt_bin = check_zt_binary()
    if not zt_bin:
        return jsonify({'status': 'not_installed', 'message': 'ZeroTier tidak terinstall di server.'})

    try:
        # Check ZT status and IP
        cmd = f"sudo {zt_bin} listnetworks"
        process = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        status = "unknown"
        zt_ip = ""
        
        for line in process.stdout.splitlines():
            if network_id in line:
                # Format: <nwid> <name> <mac> <status> <type> <dev> <ztaddr>
                parts = line.split()
                if len(parts) >= 6:
                    status = parts[3] # OK, REQUESTING_CONFIGURATION, ACCESS_DENIED, etc
                    if len(parts) >= 9:
                         # Sometimes IP is in the 8th or 9th column depending on version
                         # Let's use ip addr to be sure
                         pass

        # Robust IP detection via ip addr
        ip_cmd = "ip addr show"
        ip_process = subprocess.run(ip_cmd, shell=True, capture_output=True, text=True)
        # Search for zt interface IP
        match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+).*zt', ip_process.stdout)
        if match:
            zt_ip = match.group(1)
            # Update cache in DB
            execute_query(
                "INSERT INTO settings (setting_key, setting_value) VALUES ('zt_vps_ip', %s) "
                "ON DUPLICATE KEY UPDATE setting_value=%s",
                (zt_ip, zt_ip)
            )

        return jsonify({
            'status': status,
            'network_id': network_id,
            'ip': zt_ip
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
