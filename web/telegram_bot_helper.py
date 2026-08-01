"""Telegram inbound: polling getUpdates + perintah owner (chat tanpa login web)."""
import time
import requests
from web.database import execute_query
from web.telegram_helper import get_telegram_settings, send_telegram_message


def _count(sql):
    row = execute_query(sql, fetch_one=True) or {}
    return row.get('c', 0)


def _build_context():
    """Konteks real-time untuk /ai — deterministik (bukan buatan AI)."""
    active = _count("SELECT COUNT(*) c FROM customers WHERE status='active'")
    isolir = _count("SELECT COUNT(*) c FROM customers WHERE status='isolir'")
    online = _count("SELECT COUNT(*) c FROM active_sessions")
    piutang = _count("SELECT COUNT(*) c FROM payments WHERE status='pending'")
    router_down = _count("SELECT COUNT(*) c FROM routers WHERE status='offline'")
    voucher = _count("SELECT COUNT(*) c FROM vouchers WHERE status='unused'")
    return (f"Pelanggan aktif: {active}\nIsolir: {isolir}\nOnline: {online}\n"
            f"Piutang (pending): {piutang}\nRouter mati: {router_down}\n"
            f"Voucher sisa: {voucher}")


def _handle(text, chat_id):
    text = (text or '').strip()
    if not text or text.startswith('/start'):
        execute_query(
            "INSERT INTO settings (setting_key, setting_value) VALUES ('telegram_chat_id', %s) "
            "ON DUPLICATE KEY UPDATE setting_value=%s", (chat_id, chat_id))
        return "✅ Chat ID tersimpan. Perintah: /status, /rekap, /ai <pertanyaan>"
    if text.startswith('/status'):
        return _build_context()
    if text.startswith('/rekap'):
        row = execute_query(
            "SELECT COALESCE(SUM(amount),0) t, COUNT(*) n FROM payments "
            "WHERE status='approved' AND DATE(payment_date)=CURDATE()", fetch_one=True) or {}
        return f"Pemasukan hari ini: Rp {row.get('t',0):,.0f} ({row.get('n',0)} transaksi)"
    if text.startswith('/ai'):
        from ai_noc.deepseek_client import chat as ai_chat
        q = text[3:].strip() or 'ringkas kondisi jaringan'
        return ai_chat(
            f"Anda AI Operator MikroFun ISP. DATA REAL-TIME:\n{_build_context()}",
            q
        ) or "AI tidak tersedia (cek API key)."
    return "Perintah tidak dikenal. Coba: /status, /rekap, /ai <pertanyaan>"


def telegram_poll_loop():
    """Loop inbound — jalan sebagai thread daemon. Hanya layani chat_id pemilik."""
    print("[Telegram Bot] Polling dimulai...")
    offset = 0
    while True:
        try:
            token, chat_id = get_telegram_settings()
            if not token:
                time.sleep(10)
                continue
            r = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={'timeout': 30, 'offset': offset},
                timeout=40
            )
            for u in r.json().get('result', []):
                offset = u['update_id'] + 1
                msg = u.get('message') or {}
                sender = str(msg.get('chat', {}).get('id'))
                # Whitelist: hanya pemilik yang dilayani. TANPA INI = bocor data.
                if chat_id and sender != str(chat_id):
                    continue
                reply = _handle(msg.get('text', ''), sender)
                if reply:
                    # Teks polos: jawaban AI bisa memuat '<' atau '&' (mis.
                    # "address=<ip>"), dan dengan parse_mode HTML/Markdown
                    # Telegram menolak pesannya -> owner tidak menerima apa pun.
                    send_telegram_message(reply, parse_mode='')
        except Exception as e:
            print(f"[Telegram Bot] Error: {e}")
        time.sleep(1)
