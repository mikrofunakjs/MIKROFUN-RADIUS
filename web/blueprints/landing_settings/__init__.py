from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from web.database import execute_query
import json
import uuid

landing_settings_bp = Blueprint('landing_settings', __name__)

@landing_settings_bp.route('/', methods=['GET', 'POST'])
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    if request.method == 'POST':
        template_choice = request.form.get('template_choice', '1')
        custom_html = request.form.get('custom_html', '')
        
        # Save choice
        execute_query(
            "INSERT INTO settings (setting_key, setting_value) VALUES ('landing_page_template', %s) "
            "ON DUPLICATE KEY UPDATE setting_value=%s",
            (template_choice, template_choice)
        )
        
        # Save custom HTML
        execute_query(
            "INSERT INTO settings (setting_key, setting_value) VALUES ('landing_page_custom_html', %s) "
            "ON DUPLICATE KEY UPDATE setting_value=%s",
            (custom_html, custom_html)
        )
            
        flash('Pengaturan Landing Page berhasil disimpan.', 'success')
        return redirect(url_for('landing_settings.index'))
            
    # Load current settings
    settings_rows = execute_query("SELECT setting_key, setting_value FROM settings WHERE setting_key IN ('landing_page_template', 'landing_page_custom_html', 'landing_page_packages')", fetch=True) or []
    settings_dict = {row['setting_key']: row['setting_value'] for row in settings_rows}
    
    current_template = settings_dict.get('landing_page_template', '1')
    custom_html = settings_dict.get('landing_page_custom_html', '')
    
    packages_json = settings_dict.get('landing_page_packages', '[]')
    try:
        packages = json.loads(packages_json)
    except:
        packages = []
        
    return render_template('landing_settings/index.html', current_template=current_template, custom_html=custom_html, packages=packages)

@landing_settings_bp.route('/add-package', methods=['POST'])
def add_package():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    name = request.form.get('name')
    speed = request.form.get('speed')
    price = request.form.get('price')
    discount_price = request.form.get('discount_price', '')
    features = request.form.get('features', '') # Comma separated
    
    # Validation
    if not name or not speed or not price:
        flash('Nama, Kecepatan, dan Harga Wajib diisi.', 'error')
        return redirect(url_for('landing_settings.index'))
    
    # Get current
    row = execute_query("SELECT setting_value FROM settings WHERE setting_key = 'landing_page_packages'", fetch=True)
    try:
        packages = json.loads(row[0]['setting_value']) if row else []
    except:
        packages = []
        
    new_pkg = {
        'id': str(uuid.uuid4()),
        'name': name,
        'speed': speed,
        'price': price,
        'discount_price': discount_price,
        'features': [f.strip() for f in features.split(',')] if features else []
    }
    
    packages.append(new_pkg)
    
    # Save back
    new_json = json.dumps(packages)
    execute_query(
        "INSERT INTO settings (setting_key, setting_value) VALUES ('landing_page_packages', %s) "
        "ON DUPLICATE KEY UPDATE setting_value=%s",
        (new_json, new_json)
    )
    
    flash(f"Paket {name} berhasil ditambahkan.", 'success')
    return redirect(url_for('landing_settings.index'))

@landing_settings_bp.route('/delete-package/<pkg_id>', methods=['POST'])
def delete_package(pkg_id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    row = execute_query("SELECT setting_value FROM settings WHERE setting_key = 'landing_page_packages'", fetch=True)
    if not row:
        return redirect(url_for('landing_settings.index'))
        
    try:
        packages = json.loads(row[0]['setting_value'])
    except:
        packages = []
        
    # Filter out the deleted package
    new_packages = [p for p in packages if p.get('id') != pkg_id]
    
    new_json = json.dumps(new_packages)
    execute_query(
        "UPDATE settings SET setting_value=%s WHERE setting_key='landing_page_packages'",
        (new_json,)
    )
    
    flash("Paket berhasil dihapus.", 'success')
    return redirect(url_for('landing_settings.index'))
