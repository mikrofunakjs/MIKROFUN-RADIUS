# Draft GitHub Issues — MIKROFUN-RADIUS Bug Audit (2026-07-28)

6 bug terverifikasi (dibaca langsung dari kode, bukan tebakan). Format mengikuti gaya issue #19-#29 yang sudah ada di repo ini.

---

## Issue 1

**Title:** [CRITICAL] Error tersembunyi di accounting RADIUS bikin kuota voucher tidak pernah kepotong & sesi aktif menumpuk (stale)

**Body:**
```
## Deskripsi
Setiap kali ada pelanggan/voucher yang selesai koneksi (RADIUS Accounting-Stop, `status=2`), sistem seharusnya: (1) menghapus baris sesi dari tabel `active_sessions`, dan (2) menambah `quota_used` pada voucher sesuai byte yang terpakai. Kedua hal ini **gagal total secara diam-diam** setiap kali ada event Stop. Dampaknya:
- Voucher dengan batas kuota data (`quota_limit`) **tidak pernah** mencapai batasnya → pelanggan bisa pakai data tanpa batas walau sudah dibatasi kuotanya.
- Baris di `active_sessions` tidak pernah terhapus saat pelanggan disconnect → sesi "hantu" menumpuk terus. Ini bisa membuat pelanggan yang device-nya dibatasi (`shared_users`) tiba-tiba tidak bisa login lagi ("Batas Login Terlampaui") padahal sebenarnya tidak ada sesi aktif nyata. Dashboard admin juga akan terus menampilkan pelanggan sebagai "online" walau sudah lama disconnect.

## Root Cause
Di `simple_radius.py`, method `_update_active_session(self, status, username, nas_ip, session_id, mac_address=None)` (baris 827) dipanggil dari `handle_acct()` tanpa membawa data jumlah byte. Namun di dalam method ini, baris 908:
```python
if status == 2:
    total_bytes = input_octets + output_octets   # <-- NameError!
```
`input_octets` dan `output_octets` adalah variabel lokal milik `handle_acct()` (didefinisikan di baris 746-747), **bukan** parameter dari `_update_active_session`. Baris 908 ini melempar `NameError: name 'input_octets' is not defined`.

Karena ini terjadi di dalam blok `try` yang connection database-nya sendiri (`conn = get_db()` di baris 831, connection terpisah dari `handle_acct`), dan exception ditangkap oleh `except Exception as e: log.error(...)` di baris 919-921 tanpa `conn.commit()` sempat dijalankan (commit ada di baris 916, setelah baris yang error), maka **semua perubahan sebelumnya di transaksi ini ikut batal/rollback** saat koneksi ditutup tanpa commit — termasuk `DELETE FROM active_sessions ...` yang sudah dieksekusi di baris 893-896 untuk event Stop yang sama.

Error ini hanya muncul di log sebagai baris berulang: `DB Error _update_active_session: name 'input_octets' is not defined` — tidak ada crash yang terlihat, sehingga bug ini luput selama ini.

## Saran Perbaikan
1. Tambahkan parameter `input_octets=0, output_octets=0` ke definisi method `_update_active_session` (baris 827).
2. Update semua pemanggilan method ini di `handle_acct()` (baris 780, 795, 806) agar mengirim `input_octets` dan `output_octets` yang sudah di-parse di baris 746-747, khususnya untuk event Stop (baris 795) yang butuh nilai ini untuk update kuota.
3. Setelah fix, pastikan tidak ada lagi baris log `DB Error _update_active_session: name 'input_octets' is not defined` saat menguji dengan simulasi Accounting-Stop.
4. Sebagai pengecekan tambahan, jalankan query manual untuk memastikan `active_sessions` benar-benar terhapus setelah sesi RADIUS berakhir, dan `quota_used` pada voucher naik sesuai byte yang dipakai.
```

---

## Issue 2

**Title:** [CRITICAL] Race condition saldo Mitra/Reseller saat beli voucher — bisa dapat voucher gratis dengan spam klik

**Body:**
```
## Deskripsi
Kalau seorang Mitra/Reseller menekan tombol beli voucher dua kali dengan cepat (double click, dua tab browser, atau retry otomatis saat koneksi lambat), sistem bisa memproses kedua request tersebut dan memberikan 2 voucher meski saldo Mitra cuma cukup untuk 1. Saldo akhir yang tersimpan salah (bukan berkurang dua kali, hanya berkurang satu kali) karena kedua request saling menimpa.

## Root Cause
Di `web/blueprints/reseller/__init__.py`, function `buy()` (baris 126-174) dan `bulk_buy()` (pola yang sama, sekitar baris 371-418) melakukan pola "baca lalu tulis" (check-then-act) tanpa penguncian:
```python
balance, discount_percent = get_reseller_data()   # 1. SELECT balance
...
if buy_price > balance:                            # 2. cek di sisi Python
    ...
new_balance = balance - buy_price                  # 3. hitung saldo baru di Python
execute_query("INSERT INTO vouchers ...")           # 4. buat voucher
execute_query("UPDATE users SET balance=%s WHERE id=%s", (new_balance, session['user_id']))  # 5. timpa saldo
```
Tidak ada `SELECT ... FOR UPDATE`, tidak ada guard `WHERE balance >= buy_price`, dan update saldo di langkah 5 menimpa nilai absolut, bukan mengurangi secara atomik. Kalau dua request datang hampir bersamaan, keduanya membaca saldo yang sama di langkah 1, keduanya lolos pengecekan di langkah 2, keduanya membuat voucher di langkah 4, lalu langkah 5 dari request kedua menimpa hasil dari request pertama — saldo akhir cuma berkurang sekali walau ada 2 voucher yang dibuat.

## Saran Perbaikan
1. Ganti UPDATE saldo jadi atomik dengan guard di level SQL, contoh:
   `UPDATE users SET balance = balance - %s WHERE id = %s AND balance >= %s`
   lalu cek `rowcount` hasil query tersebut. Kalau `rowcount == 0`, artinya saldo tidak cukup (race lain sudah menghabiskannya) — batalkan pembuatan voucher (rollback transaksi) dan tampilkan pesan error, jangan lanjut insert voucher.
2. Bungkus insert voucher + update saldo dalam satu transaksi database, supaya kalau update saldo gagal, insert voucher juga ikut batal.
3. Terapkan pola yang sama di `bulk_buy()`.
```

---

## Issue 3

**Title:** [HIGH] Race condition saat top-up saldo Mitra — saldo dari salah satu pembayaran bisa hilang

**Body:**
```
## Deskripsi
Kalau ada 2 transaksi top-up saldo untuk Mitra/Reseller yang sama diproses hampir bersamaan (misalnya 2 callback webhook payment gateway datang berdekatan, atau top-up otomatis + top-up manual oleh admin terjadi bersamaan), salah satu top-up bisa "hilang" — status transaksinya tetap tercatat sukses di tabel `payments`/`reseller_transactions`, tapi saldo (`users.balance`) Mitra tidak benar-benar bertambah sesuai jumlah tersebut.

## Root Cause
Di `web/blueprints/api/__init__.py`, function `activate_reseller_topup()` (baris 370-382), dan pola yang sama di `web/blueprints/reseller_admin/__init__.py` (top-up manual oleh admin, sekitar baris 101):
```python
reseller = execute_query("SELECT balance FROM users WHERE id=%s ...")
balance_before = float(reseller['balance'])
balance_after = balance_before + float(amount)
execute_query("UPDATE users SET balance = %s WHERE id = %s", (balance_after, reseller_id))
```
Ini pola baca-lalu-tulis yang sama seperti Issue #2: saldo dibaca, dihitung di Python, lalu ditimpa dengan nilai absolut. Kalau dua proses top-up untuk reseller yang sama berjalan bersamaan, keduanya membaca saldo awal yang sama, dan yang menulis belakangan akan menimpa hasil dari yang pertama — walau kedua transaksi tercatat "berhasil" di ledger (`reseller_transactions`), saldo aktual di `users.balance` cuma bertambah sebesar salah satu dari keduanya.

## Saran Perbaikan
1. Ganti update saldo jadi atomik: `UPDATE users SET balance = balance + %s WHERE id = %s` (bukan menghitung `balance_after` di Python lalu menimpa).
2. Kalau `balance_before`/`balance_after` perlu dicatat ke ledger (`reseller_transactions`), lakukan SELECT ulang saldo *setelah* UPDATE atomik di atas selesai (dalam transaksi yang sama), bukan sebelum.
3. Terapkan perbaikan yang sama di jalur top-up manual admin (`web/blueprints/reseller_admin/__init__.py`).
```

---

## Issue 4

**Title:** [HIGH] Password Mitra/Reseller yang dibuat lewat Admin Panel tersimpan plaintext (tidak di-hash)

**Body:**
```
## Deskripsi
Saat admin menambah Mitra/Reseller baru atau mengedit passwordnya lewat menu "Kelola Mitra" (Reseller Admin), password yang dimasukkan tersimpan **apa adanya (plaintext)** di database, bukan dalam bentuk hash. Kalau database sistem ini bocor/dicuri, semua password Mitra yang dibuat/diedit lewat jalur ini akan langsung terbaca oleh siapapun.

## Root Cause
Di `web/blueprints/reseller_admin/__init__.py`:
- Function `add()` (baris 25-45):
```python
password = request.form.get('password')
...
execute_query(
    "INSERT INTO users (username, password, role, discount_percent, balance) VALUES (%s, %s, 'reseller', %s, 0)",
    (username, password, discount)
)
```
- Function `edit()` (baris 47-70), pola yang sama saat password diisi.

Password dari form langsung dimasukkan ke kolom `users.password` tanpa pernah dipanggil `generate_password_hash()`. Bandingkan dengan `web/blueprints/users/__init__.py` yang sudah benar (selalu memanggil `generate_password_hash(password)` sebelum INSERT/UPDATE).

Login Mitra masih "jalan" karena `web/blueprints/reseller/__init__.py` (baris 60-65) punya fallback:
```python
try:
    is_valid = check_password_hash(user['password'], password)
except ValueError:
    is_valid = (user['password'] == password)
```
Fallback ini seharusnya cuma untuk kompatibilitas data lama, tapi karena `reseller_admin` terus-menerus menyimpan plaintext, fallback ini jadi jalur utama untuk semua Mitra yang dibuat/diedit lewat Admin Panel — bukan pengecualian sesekali.

## Saran Perbaikan
1. Di `web/blueprints/reseller_admin/__init__.py`, import `generate_password_hash` dari `werkzeug.security`.
2. Di function `add()`: hash password sebelum INSERT — `generate_password_hash(password)`.
3. Di function `edit()`: hash password sebelum UPDATE, hanya jika field password diisi (kosongkan berarti tidak diubah, sama seperti pola di Issue lama #29).
4. Opsional (perbaikan tambahan): buat script migrasi sekali-jalan untuk mengubah semua password reseller existing yang masih plaintext di database jadi hash, supaya fallback `except ValueError` di `reseller/__init__.py` bisa dihapus setelahnya.
```

---

## Issue 5

**Title:** [MEDIUM] Session cookie pelanggan (client) menyimpan seluruh data termasuk hash password

**Body:**
```
## Deskripsi
Saat pelanggan login ke portal Client (self-service), seluruh isi baris database pelanggan tersebut — termasuk kolom `password` (hash) — disimpan ke dalam session cookie di browser pelanggan. Session cookie Flask itu **ditandatangani (signed) tapi tidak dienkripsi** (hanya base64 + tanda tangan HMAC), sehingga isinya bisa dibaca oleh siapapun yang bisa mengakses cookie tersebut — misalnya lewat celah XSS di halaman lain, komputer publik/warnet yang dipakai bergantian, atau ekstensi browser yang mencurigakan.

## Root Cause
Di `web/blueprints/client/__init__.py`:
```python
user = execute_query("SELECT * FROM customers WHERE username=%s", (username,), fetch_one=True)   # baris 34
...
session['client_user'] = user   # baris 59
```
`SELECT *` mengambil semua kolom termasuk `password`, lalu seluruh dict `user` langsung dimasukkan ke session. Bandingkan dengan blueprint lain di sistem ini (`web/blueprints/auth/__init__.py`, `tech/__init__.py`, `reseller/__init__.py`) yang sudah benar — mereka hanya menyimpan `username`, `user_id`, `role` ke session, tidak pernah menyimpan seluruh baris data termasuk password.

## Saran Perbaikan
1. Ubah baris 59 supaya hanya menyimpan data minimal yang dibutuhkan, misalnya:
   `session['client_user'] = {'id': user['id'], 'username': user['username']}`
2. Di setiap route/halaman client yang butuh data lengkap pelanggan (nama, alamat, paket, dsb), query ulang datanya dari database berdasarkan `session['client_user']['id']`, mengikuti pola yang sudah dipakai blueprint lain di sistem ini.
```

---

## Issue 6

**Title:** [LOW] Verifikasi signature webhook payment gateway tidak pakai constant-time comparison

**Body:**
```
## Deskripsi
Beberapa integrasi payment gateway memverifikasi signature/token webhook memakai operator perbandingan string biasa (`==`), bukan `hmac.compare_digest()`. Perbandingan `==` biasa berhenti di karakter pertama yang berbeda, sehingga waktu prosesnya bisa sedikit berbeda tergantung seberapa banyak karakter awal yang cocok — ini dikenal sebagai celah timing attack terhadap verifikasi signature (walau di dunia nyata cukup sulit dieksploitasi lewat jaringan karena ada jitter). Salah satu gateway di sistem ini (Moota) sudah menerapkan cara yang benar, jadi ini murni inkonsistensi yang perlu diseragamkan.

## Root Cause
Perbandingan signature pakai `==` biasa ditemukan di:
- `web/tripay_helper.py:109` — `....hexdigest() == signature_header`
- `web/midtrans_helper.py:159` — `calc_signature == signature_key`
- `web/duitku_helper.py:174` — `signature_received == signature_expected`
- `web/xendit_helper.py:103` — `callback_token == self.webhook_token`

Sementara `web/moota_helper.py:29` sudah benar menggunakan `hmac.compare_digest(...)`.

## Saran Perbaikan
Di keempat file di atas, ganti perbandingan signature/token dari `==` menjadi `hmac.compare_digest(a, b)` (tambahkan `import hmac` di bagian atas file kalau belum ada), mengikuti pola yang sudah benar di `web/moota_helper.py`. Pastikan kedua argumen `compare_digest` bertipe string atau bytes yang sama (tidak boleh campur str dan bytes).
```
