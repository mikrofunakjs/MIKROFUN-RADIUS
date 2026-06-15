# MikroFun Radius - Panduan Instalasi & Deployment

---

## A. PERSIAPAN VPS

### Minimum Requirement
- OS: Ubuntu 20.04 / Debian 11+ (recommended)
- RAM: 1 GB
- CPU: 1 core
- Port: 80 (HTTP), 443 (HTTPS), 1812-1813 (RADIUS), 3000 (WA Gateway)

### Setup VPS (Fresh Ubuntu/Debian)

```bash
# 1. Update sistem
apt update && apt upgrade -y

# 2. Install dependencies dasar
apt install -y curl wget unzip python3 python3-pip python3-venv git

# 3. Allow firewall ports
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 1812/udp
ufw allow 1813/udp
ufw allow 3000/tcp
ufw enable
```

---

## B. COPY FILE KE VPS

```bash
# Dari laptop/PC lokal, kirim semua file dist_zip/ ke VPS
scp -r dist_zip/* root@IP_VPS:/opt/mikrofun/

# Atau upload manual via SCP/WinSCP — pastikan file berikut ada di /opt/mikrofun/:
#   - install.sh
#   - mikrofun.zip
#   - schema.sql
#   - .htaccess (optional)
```

---

## C. INSTALASI

```bash
cd /opt/mikrofun
chmod +x install.sh
bash install.sh
```

Script `install.sh` akan otomatis:
1. Deteksi `mikrofun.zip` + `schema.sql` dari folder yang sama (**full local, tidak download**)
2. Exit dengan error kalau file tidak ditemukan
3. Install Python packages (Flask, mysql-connector, pycryptodome, etc)
4. Install Node.js + PM2
5. Install ZeroTier + WireGuard
6. Setup MySQL database
7. Buat systemd service `mikrofun`
8. Buat CLI shortcut `mikrofun`

**Setelah selesai:**
- Web Panel: `http://IP_VPS`
- WA Gateway: `http://IP_VPS:3000`
- Login default: `admin` / `admin`

---

## D. STRUKTUR FILE HASIL INSTALLASI

```
/opt/mikrofun/
├── .license                       # License file (portable, ikut saat copy)
├── simple_radius.py               # RADIUS server
├── web/
│   ├── app.py                     # Flask application entry
│   ├── license.so                 # License binary (compiled Cython)
│   ├── database.py                # MySQL connector
│   ├── config.py                  # Configuration (DB, RADIUS)
│   ├── decorators.py              # Decorators (premium_required, etc)
│   ├── radius_helper.py           # MikroTik API helper
│   ├── public.pem                 # RSA Public Key (cadangan)
│   ├── blueprints/                # 35+ Flask blueprints
│   │   └── settings/              # Settings + license activation
│   ├── templates/                 # HTML templates
│   └── static/                    # CSS, JS, uploads
├── wa-service/                    # WhatsApp Gateway (Node.js)
├── requirements.txt
├── database_schema.sql            # Database schema awal
└── logs/                          # Log files
```

---

## E. SETUP DATABASE MYSQL

```bash
# 1. Login MySQL
mysql -u root -p

# 2. Buat database & user
CREATE DATABASE radius_db;
CREATE USER 'radius'@'localhost' IDENTIFIED BY 'radiuspass123';
GRANT ALL PRIVILEGES ON radius_db.* TO 'radius'@'localhost';
FLUSH PRIVILEGES;
EXIT;

# 3. Import schema
mysql -u radius -p radius_db < /opt/mikrofun/database_schema.sql
```

> **Note:** Setting default username/password DB ada di `web/config.py`. Ganti sesuai kebutuhan.

---

## F. AKTIVASI LISENSI PREMIUM

```
┌─────────────────────────────────────────────┐
│  MODE FREE                                  │
│                                             │
│  • Semua fitur radius berfungsi normal       │
│  • Branding: "MikroFun"                     │
│  • Tidak bisa ubah nama ISP                 │
└─────────────────────────────────────────────┘
                 │
                 │ User beli lifetime di portal
                 │ Dapat license key
                 ▼
┌─────────────────────────────────────────────┐
│  AKTIVASI (1x saja, butuh internet)         │
│                                             │
│  1. Buka Settings > Aktivasi Lisensi        │
│  2. Masukkan license key                    │
│  3. Klik "Aktivasi Premium Sekarang"         │
│  4. System call POST /api/validate-license   │
│  5. License tersimpan di .license file       │
└─────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│  MODE PREMIUM (offline)                     │
│                                             │
│  • is_premium() = True                      │
│  • Bisa ubah nama ISP / branding sendiri    │
│  • Tidak perlu koneksi internet lagi         │
│  • License portable (ikut .license file)     │
└─────────────────────────────────────────────┘
```

**Step by Step:**

1. Buka `http://IP_VPS/settings` → tab **Aktivasi Lisensi**
2. Masukkan kode license yang dibeli dari portal
3. Klik **Aktivasi Premium**
4. Status berubah menjadi **PREMIUM EDITION**
5. Setelah aktivasi, semua fitur premium terbuka
6. File `.license` tersimpan di `/opt/mikrofun/.license`

**PENTING:** Setelah aktivasi, simpan file `.license` sebagai backup. Kalau pindah VPS, cukup copy file ini — license tetap jalan tanpa aktivasi ulang.

---

## G. CEK STATUS LISENSI

### Via Dashboard
Lihat badge di sidebar kiri:
- `BASIC` = Free mode
- `PRO` = Premium mode

### Via Command Line
```bash
cd /opt/mikrofun

# Cek apakah file .license ada
cat .license

# Cek status via Python
python3 -c "
from web.license_service import is_premium, get_isp_name
print('Premium:', is_premium())
print('ISP Name:', get_isp_name())
"
```

---

## H. MANAJEMEN SERVICE

```bash
# Lihat status
systemctl status mikrofun

# Restart web panel
systemctl restart mikrofun

# Lihat logs web
journalctl -u mikrofun -f

# Lihat logs radius
tail -f /opt/mikrofun/logs/radius.log

# Restart WA gateway
pm2 restart mikrofun-wa

# Gunakan CLI shortcut
mikrofun status
mikrofun restart
mikrofun logs
```

---

## I. PORTABLE / PINDAH VPS

Kelebihan sistem lisensi v2: **license portable**.

```bash
# Di VPS lama
cd /opt/mikrofun
tar -czf mikrofun_backup.tar.gz .license web/ static/ logs/ database_schema.sql

# Transfer ke VPS baru
scp mikrofun_backup.tar.gz root@IP_VPS_BARU:/opt/

# Di VPS baru
cd /opt
tar -xzf mikrofun_backup.tar.gz
mv /opt/mikrofun /opt/mikrofun  # sesuaikan path
cd /opt/mikrofun
bash install.sh
```

File `.license` akan ikut tercopy — lisensi tetap aktif tanpa aktivasi ulang.

---

## J. BUILD LICENSE.SO (Admin Only)

Dijalankan hanya saat release versi baru. File `license.so` di-commit ke GitHub.

```bash
# 1. Pastikan Cython tersedia
pip install cython

# 2. Jalankan build script
chmod +x build_so.sh
bash build_so.sh

# 3. Hasil: web/license.so
# 4. Commit ke GitHub (license.so ikut commit)
# 5. license_service.py ada di .gitignore (tidak ikut commit)
```

Hasil build akan membuat:
```
web/license_service.cpython-310-x86_64-linux-gnu.so
  → rename menjadi:
web/license.so
```

**Catatan:** Setiap kali ada perubahan di `license_service.py`, harus build ulang `.so` dan commit binary baru.

---

## K. TROUBLESHOOTING

### Web Panel tidak bisa diakses
```bash
systemctl status mikrofun
journalctl -u mikrofun -n 50
```

### License tidak terbaca
```bash
# Cek apakah file .license ada
ls -la /opt/mikrofun/.license

# Cek permission
chmod 644 /opt/mikrofun/.license
```

### Aktivasi gagal
- Pastikan VPS bisa konek ke `https://mikrofun.site`
- Cek: `curl -I https://mikrofun.site`
- Pastikan firewall tidak block outbound HTTPS

### "HWID Mismatch" setelah pindah VPS
- HWID dihitung dari `/etc/machine-id`
- Kalau VPS baru, perlu aktivasi ulang (atau kontak support untuk reset HWID)

---

## L. UPDATE KE VERSI BARU

```bash
cd /opt/mikrofun

# 1. Backup file .license
cp .license /tmp/.license_backup

# 2. Download versi baru
wget https://mikrofun.site/updates/mikrofun.zip -O /tmp/mikrofun_update.zip

# 3. Ekstrak (overwrite)
unzip -o /tmp/mikrofun_update.zip -d /opt/mikrofun/

# 4. Kembalikan license
cp /tmp/.license_backup /opt/mikrofun/.license

# 5. Restart service
systemctl restart mikrofun
```

---

## M. KEAMANAN SISTEM LISENSI

| Lapisan | Keterangan |
|---------|-----------|
| **Multi check point** | `is_premium()` dipanggil di 3-4 tempat berbeda (decorator, template, context processor) |
| **license.so** | Binary Cython — kode RSA & verifikasi tidak bisa dibaca |
| **RSA-2048** | Tanda tangan digital — license palsu tidak bisa dibuat |

**Apa yang BISA terjadi (dan tidak perlu dikhawatirkan):**
- Sharing `.license` antar server — ini gapapa, value jualan kita di branding
- Reverse engineering `.so` — effort > reward (target ISP kecil)
