"""
Technician Mobile Portal Blueprint
"""
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, current_app
from web.database import execute_query
from web.decorators import tech_required
import os
import time
from werkzeug.utils import secure_filename
import datetime

tech_bp = Blueprint('tech', __name__, template_folder='../../templates/tech')

@tech_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in') and session.get('role') in ['technician', 'admin']:
        return redirect(url_for('tech.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        user = execute_query(
            "SELECT * FROM users WHERE username=%s AND role IN ('technician', 'admin')",
            (username,), fetch_one=True
        )
        if user:
            from werkzeug.security import check_password_hash
            is_valid = False
            if ':' in user.get('password', ''):
                try:
                    is_valid = check_password_hash(user['password'], password)
                except Exception:
                    is_valid = (user['password'] == password)
            else:
                is_valid = (user['password'] == password)
            if is_valid:
                session['logged_in'] = True
                session['username'] = user['username']
                session['role'] = user['role']
                session['user_id'] = user.get('id', 0)
                session.permanent = True
                return redirect(url_for('tech.dashboard'))
        flash('Username atau PIN salah/tidak ditemukan.', 'error')

    return render_template('tech/login.html')

@tech_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('tech.login'))

@tech_bp.route('/dashboard')
@tech_required
def dashboard():
    user_id = session.get('user_id')
    
    # Get all jobs for this technician
    jobs = execute_query("""
        SELECT j.*, c.name as customer_name, c.address as customer_address, c.phone as customer_phone
        FROM technician_jobs j
        LEFT JOIN customers c ON j.customer_id = c.id
        WHERE j.technician_id = %s
        ORDER BY 
            j.status ASC, -- This naturally puts active jobs first if we trust ascii sorting. Better to use CASE
            CASE j.status 
                WHEN 'on_way' THEN 1 
                WHEN 'working' THEN 2 
                WHEN 'pending' THEN 3 
                WHEN 'resolved' THEN 4
                ELSE 5 
            END,
            j.priority DESC,
            j.created_at DESC
    """, (user_id,), fetch=True) or []
    
    # Simple aggregations
    active_jobs = [j for j in jobs if j['status'] in ['pending', 'on_way', 'working']]
    resolved_jobs = [j for j in jobs if j['status'] == 'resolved']
    
    return render_template('tech/index.html', 
                          active_jobs=active_jobs, 
                          resolved_jobs=resolved_jobs)

@tech_bp.route('/job/<int:job_id>', methods=['GET', 'POST'])
@tech_required
def job_detail(job_id):
    user_id = session.get('user_id')
    
    # Verify ownership
    job = execute_query("""
        SELECT j.*, c.name as customer_name, c.address as customer_address, c.phone as customer_phone
        FROM technician_jobs j
        LEFT JOIN customers c ON j.customer_id = c.id
        WHERE j.id = %s AND j.technician_id = %s
    """, (job_id, user_id), fetch_one=True)
    
    if not job:
        flash('Tugas tidak ditemukan atau Anda tidak memiliki akses.', 'error')
        return redirect(url_for('tech.dashboard'))
        
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_status':
            new_status = request.form.get('status')
            
            # Simple status updates (no photo required)
            if new_status in ['pending', 'on_way', 'working']:
                execute_query("UPDATE technician_jobs SET status=%s WHERE id=%s", (new_status, job_id))
                flash(f'Status diperbarui menjadi {new_status}', 'success')
                
            elif new_status == 'resolved':
                # RESOLVED requires photo evidence
                file1 = request.files.get('evidence_photo')
                notes = request.form.get('resolution_notes')
                
                photo_path = None
                if file1 and file1.filename:
                    ext = file1.filename.split('.')[-1]
                    filename = f"ev_{job_id}_{int(time.time())}.{ext}"
                    safe_filename = secure_filename(filename)
                    upload_target = os.path.join(current_app.config['UPLOAD_FOLDER'], safe_filename)
                    file1.save(upload_target)
                    photo_path = f"/uploads/{safe_filename}"
                    
                execute_query("""
                    UPDATE technician_jobs 
                    SET status='resolved', resolution_notes=%s, evidence_photo_1=%s, completed_at=NOW() 
                    WHERE id=%s
                """, (notes, photo_path, job_id))
                
                flash('Pekerjaan diselesaikan! Bukti telah disimpan.', 'success')
                
            return redirect(url_for('tech.job_detail', job_id=job_id))

    return render_template('tech/job.html', job=job)
