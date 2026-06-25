"""
finance_helper.py — Buku Kas Terpusat MikroFun ISP
====================================================
Semua fungsi pencatatan ke tabel `income_ledger`.
Dipanggil otomatis dari 4 titik injeksi:
  1. vouchers/add          -> record_admin_voucher()
  2. reseller/buy          -> record_mitra_voucher()
  3. billing/approve       -> record_client_payment()
  4. reseller_admin/topup  -> record_mitra_deposit()
"""
from web.database import execute_query
from decimal import Decimal, ROUND_HALF_UP
import traceback

def _insert_ledger(source_type, source_id, ref_number, description,
                   gross_amount, cost_amount, party_name, category, recorded_by, tax_amount=0):
    """Core insert ke income_ledger. Jika gagal, tulis ke failed_ledger_queue untuk retry."""
    try:
        gross = Decimal(str(gross_amount))
        cost = Decimal(str(cost_amount))
        tax = Decimal(str(tax_amount))
        net_profit = float(gross - cost)
        execute_query(
            "INSERT INTO income_ledger "
            "(source_type, source_id, ref_number, description, gross_amount, tax_amount, cost_amount, net_profit, "
            "party_name, category, recorded_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (source_type, source_id, ref_number, description,
             float(gross), float(tax), float(cost), net_profit,
             party_name, category, recorded_by)
        )
    except Exception:
        err = traceback.format_exc()
        print(f"[finance_helper] ERROR: gagal catat ledger ({source_type} src_id={source_id}):\n{err}")
        _queue_failed(source_type, source_id, ref_number, description,
                      gross_amount, cost_amount, party_name, category, recorded_by, err)

def _queue_failed(source_type, source_id, ref_number, description,
                  gross_amount, cost_amount, party_name, category, recorded_by, error):
    """Simpan ledger gagal ke tabel antrian agar tidak hilang."""
    try:
        execute_query("""
            CREATE TABLE IF NOT EXISTS failed_ledger_queue (
                id INT AUTO_INCREMENT PRIMARY KEY,
                source_type VARCHAR(32) NOT NULL,
                source_id INT NULL,
                ref_number VARCHAR(128),
                description TEXT,
                gross_amount DECIMAL(15,2),
                cost_amount DECIMAL(15,2),
                party_name VARCHAR(128),
                category VARCHAR(32),
                recorded_by VARCHAR(100),
                error_msg TEXT,
                created_at DATETIME DEFAULT NOW()
            )
        """)
        execute_query("""
            INSERT INTO failed_ledger_queue
            (source_type, source_id, ref_number, description, gross_amount, cost_amount,
             party_name, category, recorded_by, error_msg)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (source_type, source_id, ref_number, description,
              float(Decimal(str(gross_amount))), float(Decimal(str(cost_amount))),
              party_name, category, recorded_by, error[:2000]))
    except Exception as e:
        print(f"[finance_helper] FATAL: gagal menyimpan ke antrian ledger juga: {e}")


def record_admin_voucher(qty, profile, batch_name='', recorded_by='admin'):
    """Catat hasil generate voucher oleh Admin."""
    if qty <= 0:
        return
    price_per = float(profile.get('price', 0))
    gross = round(price_per * qty, 2)
    ref = batch_name if batch_name else f"BATCH-{profile.get('name', 'VOUC')}-x{qty}"
    desc = f"Generate {qty} Voucher — {profile.get('name', '-')} @ Rp {price_per:,.0f}"
    _insert_ledger(
        source_type='admin_voucher',
        source_id=None,
        ref_number=ref,
        description=desc,
        gross_amount=gross,
        cost_amount=0,
        party_name='Admin ISP',
        category='voucher',
        recorded_by=recorded_by,
    )


def record_mitra_voucher(profile, reseller_username, buy_price, voucher_code='-'):
    """Catat voucher yang dibeli Mitra (per-voucher)."""
    gross = float(profile.get('price', 0))
    cost = round(float(buy_price), 2)
    desc = f"Mitra [{reseller_username}] beli Voucher {profile.get('name', '-')} — Kode: {voucher_code}"
    _insert_ledger(
        source_type='mitra_voucher',
        source_id=None,
        ref_number=voucher_code,
        description=desc,
        gross_amount=gross,
        cost_amount=cost,
        party_name=reseller_username,
        category='voucher',
        recorded_by=reseller_username,
    )


def record_client_payment(payment, customer_name='-'):
    """Catat pembayaran tagihan pelanggan yang sudah di-Approve."""
    amount = float(payment.get('amount', 0))
    payment_id = payment.get('id')
    payment_channel = payment.get('payment_channel') or payment.get('sender_bank') or 'Manual'
    
    # Calculate PPN if profile has tax_percent
    tax_amount = 0
    profile_id = payment.get('profile_id')
    if profile_id:
        try:
            profile = execute_query("SELECT price, tax_percent FROM profiles WHERE id=%s", (profile_id,), fetch_one=True)
            if profile and profile.get('tax_percent'):
                tax_rate = float(profile['tax_percent'])
                # Tax is portion of the total: amount * tax_rate / (100 + tax_rate)
                if tax_rate > 0:
                    tax_amount = round(amount * tax_rate / (100 + tax_rate), 2)
        except Exception:
            pass
    
    desc = f"Tagihan Pelanggan [{customer_name}] — {payment_channel} — Rp {amount:,.0f}"
    _insert_ledger(
        source_type='client_payment',
        source_id=payment_id,
        ref_number=str(payment.get('external_ref') or payment_id),
        description=desc,
        gross_amount=amount,
        cost_amount=0,
        party_name=customer_name,
        category='subscription',
        recorded_by='admin',
        tax_amount=tax_amount,
    )


def record_mitra_deposit(reseller_id, reseller_name, amount, description='-'):
    """Catat masuknya deposit/top-up dari Mitra ke kas ISP."""
    amount = round(float(amount), 2)
    desc = f"Deposit Mitra [{reseller_name}] — {description}"
    _insert_ledger(
        source_type='mitra_deposit',
        source_id=reseller_id,
        ref_number=f"TOPUP-{reseller_id}",
        description=desc,
        gross_amount=amount,
        cost_amount=0,
        party_name=reseller_name,
        category='deposit',
        recorded_by='admin',
    )
