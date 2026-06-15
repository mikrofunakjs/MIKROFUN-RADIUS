import requests
import base64
import json
import hashlib
from web.database import execute_query

MIDTRANS_SNAP_SANDBOX = "https://app.sandbox.midtrans.com/snap/v1/transactions"
MIDTRANS_SNAP_PROD = "https://app.midtrans.com/snap/v1/transactions"

MIDTRANS_CORE_SANDBOX = "https://api.sandbox.midtrans.com/v2/charge"
MIDTRANS_CORE_PROD = "https://api.midtrans.com/v2/charge"

class MidtransHelper:
    def __init__(self):
        settings_rows = execute_query("SELECT * FROM settings", fetch=True) or []
        self.settings = {row['setting_key']: row['setting_value'] for row in settings_rows}
        
        self.server_key = self.settings.get('midtrans_server_key')
        self.client_key = self.settings.get('midtrans_client_key')
        self.merchant_id = self.settings.get('midtrans_merchant_id')
        self.mode = self.settings.get('midtrans_mode', 'sandbox')
        
        self.snap_url = MIDTRANS_SNAP_PROD if self.mode == 'production' else MIDTRANS_SNAP_SANDBOX
        self.core_url = MIDTRANS_CORE_PROD if self.mode == 'production' else MIDTRANS_CORE_SANDBOX

    def _get_headers(self):
        auth_string = base64.b64encode(f"{self.server_key}:".encode('utf-8')).decode('utf-8')
        return {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f"Basic {auth_string}"
        }

    def get_snap_token(self, order_id, amount, customer_data):
        """
        Get Snap Token for Popup Payment
        """
        if not self.server_key:
            return None, "Midtrans configuration missing"

        try:
            payload = {
                "transaction_details": {
                    "order_id": order_id,
                    "gross_amount": int(amount)
                },
                "customer_details": {
                    "first_name": customer_data.get('first_name'),
                    "email": customer_data.get('email'),
                    "phone": customer_data.get('phone')
                },
                "credit_card": {
                    "secure": True
                }
            }
            
            response = requests.post(self.snap_url, json=payload, headers=self._get_headers())
            data = response.json()
            
            if 'token' in data:
                return data, None
            else:
                return None, str(data)
                
        except Exception as e:
            return None, str(e)

    def create_qris_charge(self, order_id, amount, customer_data):
        """
        Create QRIS payment using Core API.
        Returns qr_string which can be rendered client-side as QR code.
        No need for user to access Midtrans domain at all!
        """
        if not self.server_key:
            return None, "Midtrans server key not configured"

        try:
            payload = {
                "payment_type": "qris",
                "transaction_details": {
                    "order_id": str(order_id),
                    "gross_amount": int(amount)
                },
                "customer_details": {
                    "first_name": customer_data.get('first_name', 'Guest'),
                    "email": customer_data.get('email', 'guest@local'),
                    "phone": customer_data.get('phone', '')
                },
                "qris": {
                    "acquirer": "gopay"
                }
            }
            
            response = requests.post(self.core_url, json=payload, headers=self._get_headers(), timeout=30)
            data = response.json()
            
            print(f"[Midtrans QRIS] Response: {json.dumps(data, indent=2)}")
            
            if data.get('status_code') == '201' or data.get('transaction_status') == 'pending':
                # Extract QR string and QR URL
                qr_string = None
                qr_url = None
                
                # Try to get from actions array
                actions = data.get('actions', [])
                for action in actions:
                    if action.get('name') == 'generate-qr-code':
                        qr_url = action.get('url')
                    elif action.get('name') == 'deeplink-redirect':
                        pass  # deeplink for mobile apps
                
                # Try direct qr_string field
                qr_string = data.get('qr_string')
                
                return {
                    'transaction_id': data.get('transaction_id'),
                    'order_id': data.get('order_id'),
                    'qr_string': qr_string,
                    'qr_url': qr_url,
                    'gross_amount': data.get('gross_amount'),
                    'expiry_time': data.get('expiry_time'),
                    'transaction_status': data.get('transaction_status')
                }, None
            else:
                error_msg = data.get('status_message', str(data))
                return None, f"Midtrans Error: {error_msg}"
                
        except requests.exceptions.Timeout:
            return None, "Midtrans API timeout. Coba lagi."
        except Exception as e:
            return None, f"Exception: {str(e)}"

    def check_transaction_status(self, order_id):
        """
        Check transaction status via Core API.
        """
        if not self.server_key:
            return None, "Configuration missing"
        
        try:
            base = "https://api.midtrans.com" if self.mode == 'production' else "https://api.sandbox.midtrans.com"
            url = f"{base}/v2/{order_id}/status"
            
            response = requests.get(url, headers=self._get_headers(), timeout=15)
            data = response.json()
            
            return data, None
        except Exception as e:
            return None, str(e)

    def verify_signature(self, order_id, status_code, gross_amount, signature_key):
        """
        Verify Notification Signature
        SHA512(order_id + status_code + gross_amount + ServerKey)
        """
        if not self.server_key: return False
        
        calc_signature = hashlib.sha512(f"{order_id}{status_code}{gross_amount}{self.server_key}".encode('utf-8')).hexdigest()
        return calc_signature == signature_key
