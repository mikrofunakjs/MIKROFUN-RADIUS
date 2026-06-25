"""
Xendit Payment Gateway Helper
Documentation: https://developers.xendit.co/api-reference/
"""
import requests
import json
import base64
from web.database import execute_query

# Xendit API base URLs
XENDIT_API_URL = "https://api.xendit.co"


class XenditHelper:
    def __init__(self):
        rows = execute_query(
            "SELECT setting_key, setting_value FROM settings WHERE setting_key IN "
            "('xendit_api_key', 'xendit_webhook_token', 'xendit_mode')",
            fetch=True
        ) or []
        settings = {r['setting_key']: r['setting_value'] for r in rows}

        self.api_key = settings.get('xendit_api_key', '')
        self.webhook_token = settings.get('xendit_webhook_token', '')
        self.mode = settings.get('xendit_mode', 'sandbox')

    def _headers(self):
        """Build auth headers for Xendit API"""
        # Xendit uses Basic auth with API key as username, empty password
        auth = base64.b64encode(f"{self.api_key}:".encode()).decode()
        return {
            'Authorization': f'Basic {auth}',
            'Content-Type': 'application/json',
        }

    def get_payment_channels(self):
        """Xendit doesn't need pre-fetching channels — returns empty.
        Payment methods are shown on Xendit invoice page dynamically."""
        return []

    def request_transaction(self, amount, customer_data, order_items,
                            return_url=None, merchant_ref=None):
        """
        Create Xendit Invoice.
        amount: Total amount (int, in IDR)
        customer_data: dict with 'first_name', 'email', 'phone'
        order_items: list of dicts
        return_url: success redirect URL
        merchant_ref: external_id for tracking
        """
        if not self.api_key:
            return None, "Xendit API Key not configured"

        try:
            external_id = merchant_ref or f"MIKROFUN-{customer_data.get('email', 'guest')}"

            payload = {
                "external_id": external_id,
                "amount": int(amount),
                "payer_email": customer_data.get('email', '') or 'guest@mikrofun.local',
                "description": order_items[0]['name'] if order_items else "Voucher MikroFun",
                "invoice_duration": 86400,
                "success_redirect_url": return_url or 'https://mikrofun.site',
                "currency": "IDR",
            }

            # Add customer info (Xendit expects given_names as string, not array)
            if customer_data.get('first_name'):
                payload["customer"] = {
                    "given_names": str(customer_data.get('first_name', '')),
                }
                if customer_data.get('phone'):
                    payload["customer"]["mobile_number"] = str(customer_data.get('phone', ''))

            url = f"{XENDIT_API_URL}/v2/invoices"
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=15)

            if resp.status_code in (200, 201):
                data = resp.json()
                return {
                    'payment_method': 'XENDIT',
                    'merchant_order_id': external_id,
                    'checkout_url': data.get('invoice_url', ''),
                    'invoice_id': data.get('id', ''),
                }, None
            else:
                try:
                    err = resp.json()
                except:
                    err = {}
                msg = err.get('message', '') or err.get('error', '') or f'HTTP {resp.status_code}'
                # Include full error for debugging
                print(f"[Xendit] Error response: {resp.text[:500]}")
                return None, msg

        except requests.exceptions.Timeout:
            return None, "Xendit API timeout"
        except Exception as e:
            return None, str(e)

    def verify_callback(self, callback_token):
        """Verify webhook callback token from Xendit"""
        return self.webhook_token and callback_token == self.webhook_token
