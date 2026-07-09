"""Auth Blueprint"""
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from web.database import execute_query
from werkzeug.security import generate_password_hash, check_password_hash
import time

auth_bp = Blueprint('auth', __name__)

_failed_logins = {}

@auth_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    # Only allow setup if there are no users at all
    try:
        user_count = execute_query("SELECT COUNT(*) as count FROM users", fetch_one=True)
        if user_count and user_count['count'] > 0:
            return redirect(url_for('auth.login'))
    except Exception as e:
        flash(f'Database not ready: {str(e)}', 'error')
        return render_template('login.html')

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if len(username) < 3 or len(password) < 4:
            flash('Username/Password is too short.', 'error')
            return redirect(url_for('auth.setup'))

        try:
            hashed_pw = generate_password_hash(password)
            execute_query(
                "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                (username, hashed_pw, 'admin')
            )
            flash('Admin account successfully created. Please log in.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            flash(f'Failed to create admin: {str(e)}', 'error')

    return render_template('setup.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    ip = request.remote_addr
    now = time.time()
    
    # Check rate limit (max 5 failed attempts per 3 minutes)
    if ip in _failed_logins:
        attempts, first_fail_time = _failed_logins[ip]
        if now - first_fail_time > 180:
            del _failed_logins[ip]
        elif attempts >= 5:
            flash('Terlalu banyak percobaan gagal. Silakan coba lagi nanti.', 'error')
            return render_template('login.html')

    # Intercept login if no users exist
    try:
        user_count = execute_query("SELECT COUNT(*) as count FROM users", fetch_one=True)
        if user_count and user_count['count'] == 0:
            return redirect(url_for('auth.setup'))
    except:
        pass # Ignore db errors here, let login fail normally
        
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        # Find user by username only
        user = execute_query(
            "SELECT * FROM users WHERE username=%s",
            (username,), fetch_one=True
        )
        
        # Check password with fallback for plain text (migration)
        is_valid = False
        if user:
            stored_pw = user['password']
            
            try:
                is_valid = check_password_hash(stored_pw, password)
            except ValueError:
                # If it's not a valid hash format, fallback to plain text comparison
                is_valid = (stored_pw == password)
                
            # Auto-upgrade to hash if it was plain text and login succeeded
            if is_valid and stored_pw == password:
                try:
                    new_hash = generate_password_hash(password)
                    execute_query("UPDATE users SET password=%s WHERE id=%s", (new_hash, user['id']))
                    print(f"DEBUG: Password for {username} auto-upgraded to hash.")
                except:
                    pass

        if is_valid:
            if ip in _failed_logins:
                del _failed_logins[ip]
                
            session['logged_in'] = True
            session['username'] = user['username']
            session['user_id'] = user['id']
            session['role'] = user['role']
            session.permanent = True
            flash('Login berhasil!', 'success')
            
            if user['role'] == 'cs':
                return redirect(url_for('cs.dashboard'))
            elif user['role'] == 'technician':
                return redirect(url_for('tech.dashboard'))
            elif user['role'] == 'reseller':
                return redirect(url_for('reseller.dashboard'))
            else:
                return redirect(url_for('index'))
        else:
            if ip not in _failed_logins:
                _failed_logins[ip] = [1, now]
            else:
                _failed_logins[ip][0] += 1
                
            # Delay to slow down brute force (max 3 seconds)
            time.sleep(min(_failed_logins[ip][0], 3))
            
            flash('Username atau password salah', 'error')

    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
