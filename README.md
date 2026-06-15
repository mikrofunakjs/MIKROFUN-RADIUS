# MikroFun Radius

**ISP Management System** — RADIUS server + Web dashboard lengkap untuk manajemen pelanggan internet (PPPoE, Hotspot, DHCP), voucher, billing, dan monitoring jaringan.

---

## Fitur

| Kategori | Fitur |
|----------|-------|
| **RADIUS** | PPPoE, Hotspot, DHCP/Static IP authentication |
| **Pelanggan** | Manajemen paket, isolir otomatis, import/export |
| **Voucher** | Generate massal, print thermal, reseller system |
| **Billing** | Payment gateway (Tripay, Duitku, Midtrans), invoice |
| **Monitoring** | Dashboard statistik, router status, active sessions |
| **Network** | MikroTik API, MikroTunnel VPN, ZeroTier, WireGuard |
| **GIS** | Peta ODP/ODC/OLT, topology visual |
| **Notifikasi** | WhatsApp Gateway (Baileys), Telegram Bot |
| **Helpdesk** | Ticketing system + dispatch teknisi |
| **Laporan** | Laporan keuangan, penjualan voucher |

---

## Instalasi

### Requirements
- **OS:** Ubuntu 20.04 / Debian 11+
- **RAM:** 1 GB minimum
- **Port:** 80 (web), 1812-1813 (RADIUS), 3000 (WA Gateway)

### 1. Clone & Install

```bash
git clone https://github.com/mikrofunakjs/MIKROFUN-RADIUS.git
cd MIKROFUN-RADIUS
sudo bash install.sh
```

`install.sh` akan otomatis:
- Install Python venv + dependencies
- Setup MySQL database
- Install Node.js + WhatsApp Gateway
- Setup systemd service
- Install WireGuard + ZeroTier
- Setup firewall (UFW)

### 2. Akses

| Service | URL | Login |
|---------|-----|-------|
| Web Panel | `http://IP_VPS` | `admin` / `admin` |
| Mikhmon | Terintegrasi di Dashboard | — |
| WA Gateway | `http://IP_VPS:3000` | — |

### 3. Setup MikroTik

Tambahkan RADIUS client di MikroTik:
```
/radius add address=IP_VPS secret=testing123 service=ppp,hotspot
/ppp aaa set use-radius=yes
```

Default RADIUS secret bisa diubah di menu **Settings > Integrasi API**.

---

## Lisensi

MikroFun Radius **open source** — semua fitur bisa digunakan dan dikembangkan secara bebas.

| Mode | Fitur | Branding |
|------|-------|----------|
| **Free** | Semua fitur jalan penuh | "MikroFun" |
| **Premium** | Semua fitur + ubah nama ISP | Nama ISP sendiri |

> Hanya **ganti nama ISP** yang memerlukan lisensi Premium — semua fitur lainnya terbuka penuh.

---

## Struktur

```
MIKROFUN-RADIUS/
├── install.sh                 # Installer 1 perintah
├── simple_radius.py           # RADIUS server
├── run_dist.py                # Entry point (web + radius)
├── web/                       # Flask web panel
│   ├── app.py                 # Main app
│   ├── blueprints/            # 35+ modul fitur
│   ├── templates/             # HTML templates
│   └── static/                # Assets
├── wa-service/                # WhatsApp gateway (Baileys)
├── mikhmonv3/                 # Mikhmon v3
├── requirements.txt
└── database_schema.sql
```

---

## Manajemen

```bash
# Cek status
systemctl status mikrofun

# Restart
systemctl restart mikrofun

# Logs
journalctl -u mikrofun -f
tail -f logs/radius.log

# CLI shortcut
mikrofun status
mikrofun restart
mikrofun logs
```

---

## Update

```bash
cd MIKROFUN-RADIUS
git pull
sudo bash install.sh
```
