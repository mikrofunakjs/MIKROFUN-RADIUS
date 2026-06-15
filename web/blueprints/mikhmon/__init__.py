"""Mikhmon Integration Blueprint with Proxy support to bypass SSL/Mixed Content issues"""
from flask import Blueprint, render_template, session, redirect, url_for, request, Response
import requests
from web.database import execute_query
import os

mikhmon_bp = Blueprint('mikhmon', __name__)

MIKHMON_LOCAL_URL = "http://127.0.0.1:8080"

@mikhmon_bp.route('/', methods=['GET', 'POST'])
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    # We use our own proxy URL so it's always HTTPS if the dashboard is HTTPS
    mikhmon_gui_url = url_for('mikhmon.proxy', path='')
    return render_template('mikhmon.html', mikhmon_url=mikhmon_gui_url, title="Mikhmon v3")

@mikhmon_bp.route('/ui/', defaults={'path': ''}, methods=['GET', 'POST'])
@mikhmon_bp.route('/ui/<path:path>', methods=['GET', 'POST'])
def proxy(path):
    if not session.get('logged_in'):
        return "Unauthorized", 403

    url = f"{MIKHMON_LOCAL_URL}/{path}"
    if request.query_string:
        url += f"?{request.query_string.decode('utf-8')}"

    # Forward the request to Mikhmon local server
    try:
        # Handle different types of POST data (form, files, etc)
        if request.method == 'POST':
            # Handle multipart/form-data (for file uploads like logos)
            if request.files:
                files = {name: (f.filename, f.read(), f.content_type) for name, f in request.files.items()}
                resp = requests.post(url, data=request.form, files=files, cookies=request.cookies, allow_redirects=False, timeout=12)
            else:
                resp = requests.post(url, data=request.form, cookies=request.cookies, allow_redirects=False, timeout=12)
        else:
            resp = requests.get(url, cookies=request.cookies, allow_redirects=False, timeout=12)
    except Exception as e:
        return f"Mikhmon Proxy Error: {str(e)}. Pastikan Mikhmon berjalan di port 8080 (sudo mikrofun mikhmon restart)", 502

    # Handle Redirects from Mikhmon
    if resp.status_code in [301, 302, 303, 307, 308]:
        loc = resp.headers.get('Location', '')
        if loc.startswith('http'):
            # If absolute, make it relative to our proxy
            new_loc = loc.replace(MIKHMON_LOCAL_URL, url_for('mikhmon.proxy', path=''))
        else:
            # If relative, just keep it, but ensure it goes through /ui/
            # Mikhmon often redirects to ./ or admin.php
            new_loc = url_for('mikhmon.proxy', path=loc.lstrip('./'))
        return redirect(new_loc)

    # Exclude certain headers
    excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
    headers = [(name, value) for (name, value) in resp.raw.headers.items()
               if name.lower() not in excluded_headers]

    return Response(resp.content, resp.status_code, headers)
