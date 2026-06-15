import requests
import hmac
import hashlib
import json
import time
from web.database import execute_query

# Tripay API Config
TRIPAY_API_URL_SANDBOX = "https://tripay.co.id/api-sandbox"
TRIPAY_API_URL_PROD = "https://tripay.co.id/api"

class TripayHelper:
    def __init__(self):
        settings_rows = execute_query("SELECT * FROM settings", fetch=True) or []
        self.settings = {row['setting_key']: row['setting_value'] for row in settings_rows}
        
        self.api_key = self.settings.get('tripay_api_key')
        self.private_key = self.settings.get('tripay_private_key')
        self.merchant_code = self.settings.get('tripay_merchant_code')
        self.mode = self.settings.get('tripay_mode', 'sandbox')
        
        self.base_url = TRIPAY_API_URL_PROD if self.mode == 'production' else TRIPAY_API_URL_SANDBOX

    def get_payment_channels(self):
        """Fetch available payment channels from Tripay"""
        if not self.api_key: return []
        
        try:
            url = f"{self.base_url}/merchant/payment-channel"
            headers = {'Authorization': f'Bearer {self.api_key}'}
            response = requests.get(url, headers=headers)
            data = response.json()
            if data['success']:
                return data['data']
            return []
        except Exception as e:
            print(f"Tripay Error: {e}")
            return []

    def request_transaction(self, method, amount, customer_data, order_items, return_url=None, merchant_ref=None):
        """
        Create a transaction
        method: Payment Channel Code (e.g. 'BRIVA')
        amount: Total amount (int)
        customer_data: dict with 'first_name', 'email', 'phone'
        order_items: list of dicts with 'name', 'price', 'quantity'
        return_url: URL to redirect user after payment attempt
        merchant_ref: Optional custom invoice ID
        """
        if not self.api_key or not self.private_key or not self.merchant_code:
            return None, "Tripay configuration missing"

        try:
            if not merchant_ref:
                merchant_ref = f"INV-{customer_data.get('id', 'u')}-{int(time.time())}"
            expiry = 24 * 60 * 60 # 24 hours
            
            payload = {
                'method': method,
                'merchant_ref': merchant_ref,
                'amount': amount,
                'customer_name': customer_data.get('first_name'),
                'customer_email': customer_data.get('email'),
                'customer_phone': customer_data.get('phone'),
                'order_items': order_items,
                'return_url': return_url or 'http://example.com/',
                'expired_time': (int(time.time()) + expiry),
                'signature': self.generate_signature(merchant_ref, amount)
            }
            
            url = f"{self.base_url}/transaction/create"
            headers = {'Authorization': f'Bearer {self.api_key}'}
            
            response = requests.post(url, json=payload, headers=headers)
            data = response.json()
            
            if data['success']:
                return data['data'], None
            else:
                return None, data.get('message', 'Unknown Error')
                
        except Exception as e:
            return None, str(e)

    def generate_signature(self, merchant_ref, amount):
        """Generate Signature for Transaction Request"""
        # merchant_code + merchant_ref + amount
        data = f"{self.merchant_code}{merchant_ref}{amount}"
        return hmac.new(
            self.private_key.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def verify_callback_signature(self, json_data, signature_header):
        """Verify Callback Signature"""
        # JSON Body Content to HMAC-SHA256
        # Tripay sends users the JSON body as the raw string to hash usually?
        # Actually Tripay doc says: HMAC-SHA256(JSON_BODY, PRIVATE_KEY)
        
        # We need the RAW JSON string exactly as received.
        # Assuming json_data is the raw string
        return hmac.new(
            self.private_key.encode('utf-8'),
            json_data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest() == signature_header

