"""Users / Staff Management Blueprint"""
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from web.database import execute_query
from web.decorators import admin_required
from werkzeug.security import generate_password_hash

users_bp = Blueprint('users', __name__, template_folder='../../templates/users')

@users_bp.route('/', methods=['GET', 'POST'])
@admin_required
def index():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            username = request.form.get('username')
            password = request.form.get('password')
            role = request.form.get('role', 'technician')
            
            exist = execute_query("SELECT id FROM users WHERE username=%s", (username,), fetch_one=True)
            if exist:
                flash("Username sudah digunakan!", "error")
            else:
                hashed_pw = generate_password_hash(password)
                execute_query(
                    "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                    (username, hashed_pw, role)
                )
                flash("Berhasil menambah staff komando.", "success")
                
        elif action == 'edit':
            user_id = request.form.get('user_id')
            username = request.form.get('username')
            password = request.form.get('password')
            role = request.form.get('role')
            
            # Keep admin role if editing the default admin
            u = execute_query("SELECT username FROM users WHERE id=%s", (user_id,), fetch_one=True)
            if u and u['username'] == 'admin':
                role = 'admin' # Force role protection
                
            if password:
                hashed_pw = generate_password_hash(password)
                execute_query("UPDATE users SET username=%s, password=%s, role=%s WHERE id=%s", 
                              (username, hashed_pw, role, user_id))
            else:
                execute_query("UPDATE users SET username=%s, role=%s WHERE id=%s", 
                              (username, role, user_id))
            flash("Data staff berhasil diupdate.", "success")
            
        elif action == 'delete':
            user_id = request.form.get('user_id')
            u = execute_query("SELECT username FROM users WHERE id=%s", (user_id,), fetch_one=True)
            if u and u['username'] == 'admin':
                flash("Akun Admin Utama (default) tidak boleh dihapus!", "error")
            else:
                execute_query("DELETE FROM users WHERE id=%s", (user_id,))
                flash("Staff berhasil dihapus dari sistem.", "success")
                
        return redirect(url_for('users.index'))

    # Display users (Admin at top, then technicians)
    users_list = execute_query("SELECT * FROM users ORDER BY role ASC, id DESC", fetch=True) or []
    
    return render_template('users/index.html', users=users_list)
