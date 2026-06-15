"""Auth Blueprint"""
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from web.database import execute_query
from werkzeug.security import generate_password_hash, check_password_hash

auth_bp = Blueprint('auth', __name__)

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
            
            # Werkzeug hashes typically contain a colon (e.g., method:salt$hash)
            if ':' in stored_pw:
                try:
                    is_valid = check_password_hash(stored_pw, password)
                except Exception as e:
                    # If it's not a valid hash, fallback to plain text comparison
                    is_valid = (stored_pw == password)
            else:
                # Definitely plain text (legacy)
                is_valid = (stored_pw == password)
                
            # Auto-upgrade to hash if it was plain text and login succeeded
            if is_valid and ':' not in stored_pw:
                try:
                    new_hash = generate_password_hash(password)
                    execute_query("UPDATE users SET password=%s WHERE id=%s", (new_hash, user['id']))
                    print(f"DEBUG: Password for {username} auto-upgraded to hash.")
                except:
                    pass

        if is_valid:
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
            flash('Username atau password salah', 'error')

    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
