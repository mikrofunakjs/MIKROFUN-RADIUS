# Changelog

## v7.5.0 (2026-06-25)

### Fitur Baru

**Xendit Payment Gateway**
- Integrasi penuh Xendit sebagai payment gateway (Invoice API + Webhook callback)
- Form konfigurasi di Settings > Payment Gateway (API Key, Webhook Token, Mode)
- Tampil di Landing Page & Client Pay dengan badge "Pembayaran via Xendit"

**PPN / Pajak pada Paket Internet**
- Field `tax_percent` (%) di Profile — opsional, default 0
- Global filter `price_total` tampil harga include PPN di semua halaman
- Live preview kalkulasi PPN di form add/edit profile
- PPN tercatat di `income_ledger.tax_amount` untuk laporan

**IP Pool Dropdown dari MikroTik**
- API endpoint `/routers/api/pools/<id>` — fetch `/ip/pool/print`
- Dropdown + tombol Fetch di form Profile (add & edit)

**Auto-Isolasi & WA Reminder (Background Service)**
- Cek PPPoE lewat jatuh tempo tiap 60 detik, auto-isolir + kick + notifikasi
- Kirim pengingat WA H-3 sebelum due_date
- Terintegrasi sebagai background thread di `run_dist.py`

**WA Gateway Auto-Start**
- Node.js Baileys auto-start via subprocess di `run_dist.py`
- `npm install` otomatis di `install.sh`

---

### Bug Fixes

**Keamanan**
- `[HIGH]` Hash password customer dengan werkzeug (fallback plaintext + auto-upgrade)
- `[HIGH]` Hash password staff/reseller/teknisi dengan werkzeug

**RADIUS Server**
- Quota voucher: increment pada STOP, bukan SUM seluruh history (fix double-count)
- Voucher timeout: `expires_at` tidak di-reset saat reconnect
- CoA port default 3799 (RFC 3576), fallback 1700

**Database**
- Hapus hardcoded `USE radius_db` dari schema.sql (fix fresh install)
- Auto-migration kolom `tax_percent`, `tax_amount`

**Web Panel**
- `cron_daily.py`: hapus SQL syntax error + dead code
- Update checker: global cache ganti session cache
- Router `direct_local`: pakai LAN IP, bukan public ISP IP
- Tech login: hapus dead code, role dari DB
- Dashboard: hapus double "Rp" prefix

**Payment**
- Client pay: amount sync untuk Xendit via onsubmit
- Client pay: `total_bill` include PPN

---

### Infrastruktur
- Apache2 auto-disabled (port 80 conflict)
- `.gitignore`: tambah `node_modules/`
- `install.sh`: auto `npm install` WA Gateway

---

## v7.4.167
- Info banner Free limit di halaman pelanggan & voucher
- Free mode limit: 100 PPPoE customers + 800 vouchers
- Fix ephemeral socket source port mismatch on RADIUS responses
