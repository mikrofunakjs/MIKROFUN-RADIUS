import hashlib
import json
import requests
import datetime
from web.database import execute_query

class DuitkuHelper:
    def __init__(self):
        settings_rows = execute_query("SELECT setting_key, setting_value FROM settings WHERE setting_key IN ('duitku_merchant_code', 'duitku_api_key', 'duitku_mode')", fetch=True) or []
        settings = {row['setting_key']: row['setting_value'] for row in settings_rows}
        
        self.merchant_code = settings.get('duitku_merchant_code', '')
        self.api_key = settings.get('duitku_api_key', '')
        self.mode = settings.get('duitku_mode', 'sandbox')
        
        if self.mode == 'production':
            self.base_url = 'https://passport.duitku.com/webapi/api/merchant/v2/inquiry'
            self.method_url = 'https://passport.duitku.com/webapi/api/merchant/paymentmethod/getpaymentmethod'
        else:
            self.base_url = 'https://sandbox.duitku.com/webapi/api/merchant/v2/inquiry'
            self.method_url = 'https://sandbox.duitku.com/webapi/api/merchant/paymentmethod/getpaymentmethod'

    def get_payment_methods(self, amount):
        if not self.api_key or not self.merchant_code:
            status_msg = "Duitku Error: Konfigurasi Merchant Code/API Key kosong."
            return [], status_msg
            
        # Strip keys to be safe
        m_code = self.merchant_code.strip()
        a_key = self.api_key.strip()
        
        now = datetime.datetime.now()
        ts_pretty = now.strftime('%Y-%m-%d %H:%M:%S')
        ts_raw = now.strftime('%Y%m%d%H%M%S')
        int_amount = int(float(amount))
        
        # Variations: (Label, Algorithm, Timestamp, SignaturePartsOrder, CaseMapping)
        # Order 1: MC + AMT + TS + KEY (Customary)
        # Order 2: MC + TS + AMT + KEY (Alternative)
        # Order 3: MC + TS + KEY (No Amount)
        variations = [
            ('V2-SHA256-A', 'SHA256', ts_pretty, [m_code, int_amount, ts_pretty, a_key], {'mc': 'merchantCode', 'am': 'paymentAmount', 'dt': 'dateTime'}),
            ('V2-MD5-A', 'MD5', ts_pretty, [m_code, int_amount, ts_pretty, a_key], {'mc': 'merchantCode', 'am': 'paymentAmount', 'dt': 'dateTime'}),
            ('V2-MD5-B', 'MD5', ts_pretty, [m_code, ts_pretty, int_amount, a_key], {'mc': 'merchantCode', 'am': 'paymentAmount', 'dt': 'dateTime'}),
            ('V2-NoAmt', 'SHA256', ts_pretty, [m_code, ts_pretty, a_key], {'mc': 'merchantCode', 'am': 'paymentAmount', 'dt': 'dateTime'}),
            ('V1-MD5-A', 'MD5', ts_raw, [m_code, int_amount, ts_raw, a_key], {'mc': 'merchantCode', 'am': 'paymentAmount', 'dt': 'dateTime'}),
            ('Legacy', 'MD5', ts_raw, [m_code, int_amount, ts_raw, a_key], {'mc': 'merchantcode', 'am': 'amount', 'dt': 'datetime'}),
        ]
        
        last_error = "Metode pembayaran tidak tersedia."
        
        for name, algo, ts, sig_parts, keys in variations:
            # Generate Request String for Signature
            sig_str = "".join([str(p) for p in sig_parts])
            
            if algo == 'SHA256':
                sig = hashlib.sha256(sig_str.encode('utf-8')).hexdigest()
            else:
                sig = hashlib.md5(sig_str.encode('utf-8')).hexdigest()
                
            payload = {
                keys['mc']: m_code,
                keys['am']: int_amount,
                keys['dt']: ts,
                "signature": sig
            }
            
            try:
                response = requests.post(self.method_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
                try:
                    data = response.json()
                except:
                    last_error = f"Duitku ({name}): Response Not JSON (HTTP {response.status_code})"
                    continue

                if data.get('responseCode') == '00' or data.get('statusCode') == '00':
                    return data.get('paymentFee', []), None
                else:
                    msg = data.get('responseMessage') or data.get('statusMessage') or data.get('message') or data.get('Message') or "Error"
                    code = data.get('responseCode') or data.get('statusCode') or data.get('code') or "None"
                    
                    if code == "None" and msg == "Error":
                        last_error = f"Duitku ({name}): Keys: {list(data.keys())}"
                    else:
                        last_error = f"Duitku ({name}): {msg} (Code: {code})"
                    
                    print(f"DEBUG Duitku Fail ({name}): {last_error}")
            except Exception as e:
                last_error = f"Duitku System Error: {str(e)}"
                
        return [], last_error

    def request_transaction(self, method, amount, customer, items, callback_url, return_url, merchant_order_id=None):
        if not self.api_key or not self.merchant_code:
            return None, "Duitku API credentials not configured"
            
        if not merchant_order_id:
            merchant_order_id = f"DTK-{customer['id']}-{int(datetime.datetime.now().timestamp())}"
        
        # Signature V2 = sha256(merchantCode + merchantOrderId + amount + apiKey)
        signature_string = f"{self.merchant_code}{merchant_order_id}{amount}{self.api_key}"
        signature = hashlib.sha256(signature_string.encode('utf-8')).hexdigest()
        
        # Duitku format requires price as int
        item_details = []
        for item in items:
            item_details.append({
                'name': item['name'],
                'price': int(item['price']),
                'quantity': int(item['quantity'])
            })
            
        payload = {
            'merchantCode': self.merchant_code,
            'paymentAmount': int(amount),
            'paymentMethod': method,
            'merchantOrderId': merchant_order_id,
            'productDetails': items[0]['name'] if items else 'Internet Payment',
            'additionalParam': '',
            'merchantUserInfo': str(customer['id']),
            'customerVaName': customer.get('first_name', 'Bpk/Ibu'),
            'email': customer.get('email', f"user{customer['id']}@example.com"),
            'phoneNumber': customer.get('phone', '081234567890'),
            'itemDetails': item_details,
            'customerDetail': {
                'firstName': customer.get('first_name', 'Bpk/Ibu'),
                'lastName': '',
                'email': customer.get('email', f"user{customer['id']}@example.com"),
                'phoneNumber': customer.get('phone', '081234567890'),
            },
            'callbackUrl': callback_url,
            'returnUrl': return_url,
            'signature': signature,
            'expiryPeriod': 1440 # 24 hours
        }
        
        try:
            print(f"DEBUG: Duitku Inquiry Transaction: {self.base_url}")
            response = requests.post(
                self.base_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            data = response.json()
            print(f"DEBUG: Duitku Trx Response: {data}")
            
            if data.get('statusCode') == '00':
                return {
                    'reference': data.get('reference'),
                    'payment_method': method,
                    'checkout_url': data.get('paymentUrl'),
                    'merchant_order_id': merchant_order_id
                }, None
            else:
                return None, f"Error: {data.get('statusMessage')}"
                
        except Exception as e:
            return None, str(e)
            
    def verify_callback(self, data):
        """
        Verify Duitku Callback
        Signature = md5(merchantCode + amount + merchantOrderId + apiKey)
        """
        merchant_code = data.get('merchantCode')
        amount = data.get('amount')
        merchant_order_id = data.get('merchantOrderId')
        signature_received = data.get('signature')
        
        signature_string = f"{self.merchant_code}{amount}{merchant_order_id}{self.api_key}"
        signature_expected = hashlib.md5(signature_string.encode('utf-8')).hexdigest()
        
        return signature_received == signature_expected
