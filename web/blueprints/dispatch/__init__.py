"""
Dispatch / Job Order Management Blueprint
"""
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from web.database import execute_query
from web.decorators import admin_required
import datetime

dispatch_bp = Blueprint('dispatch', __name__, template_folder='../../templates/dispatch')

@dispatch_bp.route('/', methods=['GET', 'POST'])
@admin_required
def index():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            ticket_id = request.form.get('ticket_id') or None
            customer_id = request.form.get('customer_id') or None
            technician_id = request.form.get('technician_id') or None
            job_type = request.form.get('job_type')
            title = request.form.get('title')
            description = request.form.get('description')
            priority = request.form.get('priority', 'medium')
            created_by = session.get('user_id')
            
            execute_query("""
                INSERT INTO technician_jobs 
                (ticket_id, customer_id, technician_id, job_type, title, description, priority, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (ticket_id, customer_id, technician_id, job_type, title, description, priority, created_by))
            flash('Tugas baru berhasil ditugaskan ke Teknisi!', 'success')
            
        elif action == 'edit':
            job_id = request.form.get('job_id')
            customer_id = request.form.get('customer_id') or None
            technician_id = request.form.get('technician_id') or None
            job_type = request.form.get('job_type')
            title = request.form.get('title')
            description = request.form.get('description')
            priority = request.form.get('priority')
            status = request.form.get('status')
            
            execute_query("""
                UPDATE technician_jobs SET
                customer_id=%s, technician_id=%s, job_type=%s, title=%s, description=%s, 
                priority=%s, status=%s
                WHERE id=%s
            """, (customer_id, technician_id, job_type, title, description, priority, status, job_id))
            flash('Data tugas berhasil diupdate.', 'success')
            
        elif action == 'delete':
            job_id = request.form.get('job_id')
            execute_query("DELETE FROM technician_jobs WHERE id=%s", (job_id,))
            flash('Data tugas berhasil dihapus.', 'success')
            
        return redirect(url_for('dispatch.index'))

    # Load data for rendering
    jobs = execute_query("""
        SELECT j.*, 
               t.username as technician_name,
               c.name as customer_name,
               c.address as customer_address,
               a.username as admin_name
        FROM technician_jobs j
        LEFT JOIN users t ON j.technician_id = t.id
        LEFT JOIN customers c ON j.customer_id = c.id
        LEFT JOIN users a ON j.created_by = a.id
        ORDER BY 
            CASE j.priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
            j.created_at DESC
    """, fetch=True) or []
    
    technicians = execute_query("SELECT id, username FROM users WHERE role='technician'", fetch=True) or []
    customers = execute_query("SELECT id, name, address FROM customers ORDER BY name ASC", fetch=True) or []

    return render_template('dispatch/index.html', jobs=jobs, technicians=technicians, customers=customers)
