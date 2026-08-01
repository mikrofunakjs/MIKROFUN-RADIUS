from flask import Blueprint, render_template, session, redirect, url_for
from web.decorators import staff_required

docs_bp = Blueprint('docs', __name__)

@docs_bp.route('/')
@staff_required
def index():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
        
    return render_template('docs/index.html')
