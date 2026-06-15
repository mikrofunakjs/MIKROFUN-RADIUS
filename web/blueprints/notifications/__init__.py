from flask import Blueprint, jsonify, request, session, redirect, url_for
from web.database import execute_query

notifications_bp = Blueprint('notifications', __name__)

@notifications_bp.route('/api/unread')
def get_unread():
    """Get unread notifications count and latest items"""
    if not session.get('logged_in'):
        return jsonify({'count': 0, 'items': []})
        
    # Get count
    count_res = execute_query(
        "SELECT COUNT(*) as c FROM notifications WHERE is_read = 0", 
        fetch_one=True
    )
    count = count_res['c'] if count_res else 0
    
    # Get latest 5 unread (or recent if all read?)
    # Let's show latset 5 unread, or if 0 unread, show latest 5 history
    items = execute_query(
        "SELECT * FROM notifications ORDER BY created_at DESC LIMIT 5",
        fetch=True
    ) or []
    
    return jsonify({
        'count': count,
        'items': items
    })

@notifications_bp.route('/api/mark_read', methods=['POST'])
def mark_read():
    """Mark all or specific notification as read"""
    if not session.get('logged_in'):
        return jsonify({'status': 'error'})
        
    req = request.json or {}
    notif_id = req.get('id')
    
    if notif_id:
        execute_query("UPDATE notifications SET is_read=1 WHERE id=%s", (notif_id,))
    else:
        # Mark all
        execute_query("UPDATE notifications SET is_read=1 WHERE is_read=0")
        
    return jsonify({'status': 'success'})

# Helper function to be imported by other modules
def add_notification(title, message, category='info'):
    try:
        execute_query(
            "INSERT INTO notifications (title, message, category) VALUES (%s, %s, %s)",
            (title, message, category)
        )
    except Exception as e:
        print(f"Failed to add notification: {e}")
