from functools import wraps
from flask import redirect, url_for, flash, session
from web.license_service import is_premium

def premium_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_premium():
            flash('Fitur ini hanya tersedia untuk versi PREMIUM. Silakan aktivasi lisensi.', 'error')
            return redirect(url_for('settings.index'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in') or session.get('role') != 'admin':
            flash('Akses ditolak. Menu ini hanya untuk Administrator/Pemilik.', 'error')
            return redirect(url_for('cs.dashboard') if session.get('role') == 'cs' else url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def cs_or_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in') or session.get('role') not in ['admin', 'cs']:
            flash('Akses ditolak. Anda harus login sebagai CS atau Admin.', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def tech_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in') or session.get('role') not in ['admin', 'technician']:
            flash('Akses ditolak. Silakan login terlebih dahulu.', 'error')
            return redirect(url_for('tech.login'))
        return f(*args, **kwargs)
    return decorated_function
