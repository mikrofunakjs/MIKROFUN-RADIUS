import hmac
import hashlib
import json
from web.database import execute_query

class MootaHelper:
    def __init__(self):
        settings_rows = execute_query("SELECT setting_key, setting_value FROM settings WHERE setting_key IN ('moota_webhook_secret', 'moota_api_key')", fetch=True) or []
        settings = {row['setting_key']: row['setting_value'] for row in settings_rows}
        self.webhook_secret = settings.get('moota_webhook_secret', '')
        self.api_key = settings.get('moota_api_key', '')

    def verify_webhook_signature(self, signature_header, payload_body):
        """
        Verify Moota webhook signature using HMAC-SHA256
        payload_body must be the raw request string
        """
        if not self.webhook_secret:
            return False
            
        # Ensure payload is a string (if it's bytes, decode it)
        if isinstance(payload_body, bytes):
            payload_body = payload_body.decode('utf-8')
            
        mac = hmac.new(self.webhook_secret.encode('utf-8'), payload_body.encode('utf-8'), hashlib.sha256)
        expected_signature = mac.hexdigest()
        
        # Safe comparison to prevent timing attacks
        return hmac.compare_digest(expected_signature, signature_header)
