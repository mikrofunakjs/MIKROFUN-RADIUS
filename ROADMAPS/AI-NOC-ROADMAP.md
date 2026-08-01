# MIKROFUN AI NOC — ROADMAP

> **Visi:** MikroFun bukan lagi sekadar RADIUS + Billing. MikroFun menjadi **platform ISP all-in-one** dengan AI Network Operations Center (NOC) yang menggantikan peran engineer manusia — monitoring, diagnosa, eksekusi, dan prediksi — untuk ISP besar maupun RT/RW Net kecil.

---

## GOALS

| # | Goal | Ukuran Keberhasilan |
|---|------|---------------------|
| 1 | ISP kecil gak perlu sewa NOC engineer | AI handle 80% masalah tanpa intervensi manusia |
| 2 | ISP besar bisa pantau 1000+ router dari 1 dashboard | 1 server MikroFun kelola 1000 router MikroTik |
| 3 | Troubleshooting 10x lebih cepat | AI diagnosa akurat dalam <5 detik |
| 4 | Gak ada router mati gak ketahuan | Deteksi offline + alert real-time |
| 5 | Pelanggan puas, churn turun | AI CS jawab komplain WA 24/7 |
| 6 | Biaya operasional turun drastis | 1 admin gantikan 5 NOC engineer |

---

## ARSITEKTUR

```
┌─────────────────────────────────────────────────────────────┐
│                    SERVER MIKROFUN + AI NOC                  │
│                                                              │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ MikroFun  │  │  AI NOC Core │  │  Knowledge Base        │ │
│  │ RADIUS    │  │              │  │  (Runbook, solusi,      │ │
│  │ Billing   │  │ ┌──────────┐ │  │   gejala→penyebab→solusi)│
│  │ Portal    │  │ │ Rules    │ │  │                        │ │
│  │ API       │  │ │ Engine   │ │  └────────────────────────┘ │
│  └─────┬─────┘  │ │ (80%)    │ │                              │
│        │        │ ├──────────┤ │                              │
│        │        │ │ DeepSeek │ │                              │
│        │        │ │ API      │ │                              │
│        │        │ │ (20%)    │ │                              │
│        │        │ └──────────┘ │                              │
│        │        └──────┬───────┘                              │
│        │               │                                      │
│  ┌─────▼───────────────▼────────────────────────────────────┐ │
│  │              DATA LAYER (MySQL radius_db)                 │ │
│  │                                                           │ │
│  │  radacct │ active_sessions │ radacct_snapshots │ ai_*     │ │
│  │  customers │ vouchers │ profiles │ routers │ settings     │ │
│  └───────────────────────────────────────────────────────────┘ │
│                              │                                 │
│  ┌───────────────────────────▼─────────────────────────────┐  │
│  │              MIKROTIK API POOL                           │  │
│  │  Async, parallel, via WireGuard mesh                     │  │
│  │  (CPU, memori, interface, signal, log, netwatch)         │  │
│  └───────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                              │
                    WireGuard Mesh VPN
                    (stabil, low latency)
                              │
      ┌───────────┬───────────┼───────────┬───────────┐
      │           │           │           │           │
   ┌──▼──┐    ┌──▼──┐    ┌──▼──┐    ┌──▼──┐    ┌──▼──┐
   │RT 01│    │RT 02│    │RT 03│    │RT 04│    │RT ..N│
   └─────┘    └─────┘    └─────┘    └─────┘    └─────┘
```

---

## SUMBER DATA

### Data yang sudah ada (RADIUS):
| Sumber | Data | Frekuensi | Disimpan di |
|--------|------|-----------|-------------|
| RADIUS Auth | Username, MAC, password | Saat login | customers, active_sessions |
| RADIUS Acct Start | Session ID, IP, MAC | Saat login | radacct, active_sessions |
| RADIUS Interim Update | Upload bytes, download bytes, session time, IP | Tiap 5 menit | radacct (overwrite) |
| RADIUS Acct Stop | Total bytes, total time, terminate cause | Saat logout | radacct (final) |
| RADIUS Acct On/Off | Router reboot | Saat reboot | trigger reset |

### Data yang akan ditambah (baru):
| Sumber | Data | Frekuensi | Tabel Baru |
|--------|------|-----------|------------|
| RADIUS Interim | Traffic per snapshot | Tiap 5 menit | `radacct_snapshots` |
| MikroTik API | CPU, memory, disk, uptime | Tiap 5 menit | `router_metrics` |
| MikroTik API | Interface traffic, errors | Tiap 5 menit | `interface_metrics` |
| MikroTik API | Wireless signal, CCQ, noise | Tiap 10 menit | `wireless_metrics` |
| MikroTik API | DHCP leases, ARP table | Tiap 10 menit | `device_inventory` |
| MikroTik API | System logs | Real-time stream | `router_logs` |

---

## AI ENGINE: HYBRID APPROACH

```
┌─────────────────────────────────────────────────────────────┐
│                     AI NOC ENGINE                            │
│                                                              │
│  ┌──────────────────┐   ┌──────────────────┐                │
│  │   RULES ENGINE    │   │   DEEPSEEK API   │                │
│  │   (Local, 0 token)│   │   (Cloud, token) │                │
│  │                    │   │                  │                │
│  │ • CPU >90% ?      │   │ • Diagnosa        │                │
│  │ • Interface down? │   │   kompleks        │                │
│  │ • User expired?   │   │ • WA natural       │                │
│  │ • Router offline? │   │ • Laporan insight │                │
│  │ • Bandwidth >80%? │   │ • Root cause       │                │
│  │ • Disk >90%?      │   │ • Escalation msg  │                │
│  │                    │   │                  │                │
│  │ 80% kasus          │   │ 20% kasus        │                │
│  │ 0 token, <10ms     │   │ ~Rp 300/bln      │                │
│  └────────┬───────────┘   └────────┬─────────┘                │
│           │                        │                          │
│           └────────┬───────────────┘                          │
│                    │                                          │
│           ┌────────▼─────────┐                                │
│           │  DECISION ENGINE  │                               │
│           │  (eskalasi,       │                               │
│           │   confidence,     │                               │
│           │   auto/manual)    │                               │
│           └────────┬─────────┘                                │
│                    │                                          │
│     ┌──────────────┼──────────────┐                           │
│     │              │              │                           │
│  ┌──▼──┐     ┌─────▼────┐   ┌────▼────┐                       │
│  │ Auto│     │Rekomendasi│   │Escalate │                      │
│  │Fix  │     │ke Admin   │   │ke Admin │                      │
│  │conf>│     │conf 60-85%│   │conf<60%│                       │
│  │85%  │     │           │   │         │                      │
│  └─────┘     └───────────┘   └─────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

### Biaya Token DeepSeek (estimasi realistis):

| Skala | Pelanggan | Token/bulan | Biaya/bulan |
|-------|-----------|-------------|-------------|
| RT/RW Net | 50 | ~25.000 | ~Rp 100 |
| RT/RW Net | 200 | ~85.000 | ~Rp 300 |
| ISP Kecil | 1.000 | ~400.000 | ~Rp 1.500 |
| ISP Menengah | 5.000 | ~2.000.000 | ~Rp 8.000 |
| ISP Besar | 50.000 | ~20.000.000 | ~Rp 80.000 |

**Model:** deepseek-chat ($0.14/1M input, $0.28/1M output)

---

## FASE PENGEMBANGAN

### FASE 0 — DATA FOUNDATION (Minggu 1-2)
> Menyiapkan data pipeline. AI gak akan pintar tanpa data.

**Tasks:**
- [ ] **radacct_snapshots table** — Simpan setiap INTERIM UPDATE sebagai snapshot, bukan overwrite
  - File: `simple_radius.py` baris 797-806 (handle_acct interim update)
  - Tambah 1 table + 1 INSERT setiap interim update
- [ ] **router_metrics table** — CPU, memory, disk, uptime router
  - File baru: `router_metrics_collector.py` (pull via MikroTik API tiap 5 menit)
- [ ] **ai_decisions table** — Log semua keputusan AI
  - Fields: decision_type, target, reason, confidence, executed_at, admin_override
- [ ] **ai_knowledge table** — Runbook: gejala → penyebab → solusi
  - Fields: symptom, cause, probability, check_command, solution, auto_execute

**Deliverable:** Data pipeline siap, `radacct_snapshots` terisi otomatis, dashboard monitoring dasar.

---

### FASE 1 — AI NOC BASIC (Minggu 3-4)
> Monitoring + Alert + Diagnosis Dasar. Ganti The Dude & Zabbix.

**Features:**
- [ ] **Router monitoring real-time**
  - Online/offline detection (<30 detik)
  - CPU, memory, disk usage alert
  - Interface up/down, traffic, errors
- [ ] **Client monitoring**
  - Siapa online, dari router mana, sinyal berapa
  - Traffic per user (dari radacct_snapshots)
  - Anomali traffic detection
- [ ] **Rules Engine** (80% kasus, 0 token)
  - Threshold-based alerts (CPU >90% → warning)
  - Simple actions (interface down → alert WA)
  - Auto restart interface stuck
- [ ] **AI Reports harian**
  - DeepSeek generate ringkasan: jumlah user, insiden, rekomendasi
  - Kirim via WA/Telegram jam 06:00

**Integration points:**
- `simple_radius.py` → tambah interim snapshot
- `monitor_router_status.py` → upgrade jadi multi-router + metrics
- `wa_reminder.py` → tambah channel alert
- File baru: `ai_noc_rules.py`, `ai_noc_reporter.py`

**Deliverable:** Dashboard NOC, alert real-time, laporan harian otomatis.

---

### FASE 2 — AI DIAGNOSIS + AUTO RESOLUTION (Minggu 5-7)
> AI yang bisa diagnosa dan eksekusi perbaikan.

**Features:**
- [ ] **Root cause analysis**
  - "Internet lambat" → AI cek: signal? bandwidth? interference? CPU? log error?
  - Input: sympton dari user → Output: root cause + confidence score
- [ ] **Knowledge base runbook**
  - 50+ skenario umum MikroTik troubleshooting
  - Format: gejala → penyebab → solusi → auto/manual
  - Learning: tiap kasus sukses auto terekam
- [ ] **Auto-fix engine**
  - Confidence >85% → eksekusi otomatis
  - Channel interference → auto pindah channel
  - DHCP conflict → auto release-reassign
  - Queue tree mampet → auto reset
- [ ] **AI Customer Service (WhatsApp)**
  - DeepSeek baca WA masuk → diagnosa → jawab natural
  - "Pak internet mati" → AI cek status user → jawab "Sedang ada gangguan di router Blok A, sedang kami perbaiki."
  - Integrasi: `wa_service` / Baileys gateway

**Integration points:**
- File baru: `ai_noc_diagnosis.py`, `ai_noc_executor.py`
- File baru: `ai_cs_whatsapp.py` (integrasi WA gateway)
- `wa_reminder.py` → tambah bidirectional chat

**Deliverable:** AI diagnosa akurat, auto-fix 50+ skenario, AI CS via WhatsApp.

---

### FASE 3 — PREDICTIVE NOC + MULTI-TENANT (Minggu 8-10)
> AI memprediksi sebelum masalah terjadi.

**Features:**
- [ ] **Predictive maintenance**
  - Prediksi interface error rate naik → rekomendasi ganti kabel
  - Prediksi router bakal mati → preemptive alert
  - Prediksi disk penuh → auto cleanup log
- [ ] **Capacity planning**
  - Prediksi kapan bandwidth perlu upgrade
  - Rekomendasi penambahan router/AP berdasarkan pertumbuhan user
- [ ] **Churn prediction**
  - AI deteksi sinyal pelanggan mau kabur (telat 3x, komplain tinggi)
  - Auto retention offer (diskon, upgrade gratis 1 bulan)
- [ ] **Multi-tenant support**
  - Satu server MikroFun melayani 10 ISP berbeda
  - Isolasi data per tenant
  - AI NOC per-tenant dengan knowledge base terpisah

**Integration points:**
- File baru: `ai_noc_predictor.py`
- `web/blueprints/` → tambah tenant management

**Deliverable:** Prediksi akurat, capacity planning, multi-tenant ready.

---

### FASE 4 — MARKETPLACE & ECOSYSTEM (Minggu 11-12)
> MikroFun jadi platform, bukan cuma software.

**Features:**
- [ ] **Runbook marketplace**
  - ISP bisa sharing knowledge base
  - Rating & review runbook
  - Verified by MikroFun
- [ ] **AI model fine-tuning**
  - Model belajar dari ribuan kasus nyata
  - Model khusus MikroTik troubleshooting
- [ ] **White-label dashboard**
  - ISP bisa branding sendiri
  - Embed ke website ISP
  - Custom domain

---

## INTEGRATION MAP (File yang Disentuh)

```
MIKROFUN-RADIUS/
│
├── simple_radius.py          ← [MODIFY] Fase 0: tambah radacct_snapshots
├── run_dist.py               ← [MODIFY] Fase 0: tambah AI thread
├── monitor_router_status.py   ← [REWRITE] Fase 1: multi-router + metrics
├── auto_isolate.py            ← [MODIFY] Fase 2: AI-based decision
├── wa_reminder.py             ← [MODIFY] Fase 2: bidirectional AI CS
├── cleanup_vouchers.py        ← [NO CHANGE]
│
├── web/
│   ├── database.py            ← [NO CHANGE]
│   ├── config.py              ← [MODIFY] tambah DeepSeek API key config
│   ├── app.py                 ← [MODIFY] tambah AI blueprint
│   ├── mikrotik_api.py        ← [MODIFY] Fase 1: async pool
│   │
│   └── blueprints/
│       ├── api/__init__.py    ← [MODIFY] Fase 1: endpoint AI
│       └── [NEW] ai/          ← [NEW] AI dashboard blueprint
│
├── [NEW] ai_noc/
│   ├── __init__.py
│   ├── rules_engine.py        ← Fase 1: threshold + simple actions
│   ├── deepseek_client.py     ← Fase 1: DeepSeek API wrapper
│   ├── diagnosis_engine.py    ← Fase 2: root cause analysis
│   ├── executor.py            ← Fase 2: auto-fix via MikroTik API
│   ├── predictor.py           ← Fase 3: predictive analysis
│   ├── reporter.py            ← Fase 1: daily report generator
│   └── knowledge_base.py      ← Fase 2: runbook management
│
└── database/
    ├── [NEW] ai_noc_schema.sql     ← Semua tabel AI
    └── migrations.py               ← [MODIFY] tambah migration AI
```

---

## METRICS KEBERHASILAN

| Metric | Baseline | Target Fase 1 | Target Fase 2 | Target Fase 4 |
|--------|----------|---------------|---------------|---------------|
| Waktu deteksi router offline | 10 menit | <30 detik | <10 detik | <5 detik |
| Troubleshooting resolution | 30 menit | 10 menit | 2 menit | 30 detik |
| Kasus selesai auto (no human) | 0% | 30% | 60% | 80% |
| False positive alerts | - | <10% | <5% | <2% |
| CS response time | 2 jam | 5 menit | 30 detik | <10 detik |
| Churn rate | - | - | -15% | -30% |
| Biaya operasional/1000 user | - | -20% | -40% | -60% |

---

## DEPENDENSI TEKNIS

| Teknologi | Versi | Fungsi |
|-----------|-------|--------|
| Python | 3.10+ | AI engine |
| MySQL | 5.7+ | Data storage |
| DeepSeek API | v1 | AI inference |
| MikroTik RouterOS | v7.10+ | Target devices |
| WireGuard | built-in | VPN mesh |
| Cloudflare Tunnel | latest | Public access |
| Baileys (WA) | latest | WhatsApp gateway |

---

## CATATAN PENTING

1. **RADIUS Interim snapshots adalah kunci.** Tanpa time-series traffic data, AI gak bisa analisa pola.
2. **Rules engine dulu sebelum AI.** 80% masalah ISP itu deterministik — threshold CPU, interface down, user expired. Rules engine handle ini tanpa token.
3. **DeepSeek hanya untuk bahasa natural.** Diagnosa kompleks, laporan insight, WA customer service.
4. **Confidence threshold kritis.** Jangan auto-fix kalau confidence <85%. Risiko terlalu besar.
5. **Knowledge base hidup.** Setiap diagnosa sukses → auto terekam. Setiap gagal → admin update manual.
6. **WireGuard mesh wajib.** Tanpa VPN stabil, AI gak bisa akses MikroTik API dari server pusat.

---

*Roadmap ini hidup. Update setiap fase selesai. Tanggal target disesuaikan dengan kecepatan development.*
