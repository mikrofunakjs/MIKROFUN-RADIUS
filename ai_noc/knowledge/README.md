# Knowledge Base AI MikroFun

Folder ini berisi catatan teknis milik owner (MikroTik, jaringan, troubleshooting,
kebijakan usaha). Pola kerja AI: **sebelum menjawab, AI cek knowledge ini dulu** —
pertanyaan dipakai untuk memilih file yang paling relevan (kata kunci), lalu AI
menjawab berdasarkan file itu. Kalau jawabannya tidak ada di catatan, AI wajib
mengakuinya (tidak mengarang).

## Cara pakai
1. Buat file baru: `topik-singkat.md` (contoh: `mikrotik-dasar.md`, `troubleshooting-pppoe.md`).
2. Tulis bebas — bahasa Indonesia boleh. Format bebas, makin rapi makin bagus:
   - Mulai dengan judul `# Nama Topik`
   - Pakai pertanyaan-jawaban untuk hal yang sering ditanya
   - Pakai langkah bernomor untuk cara konfigurasi / troubleshooting
   - Semakin sering kata kunci pertanyaan muncul di file, semakin besar peluang file itu dipilih
3. Simpan. Tidak perlu restart — perubahan langsung terbaca.

## Batas
- AI memilih maksimal 2 file teratas (env `KNOWLEDGE_TOP_N`), total ± 12.000 karakter
  (env `KNOWLEDGE_BUDGET_CHARS`).
- Skor kata kunci itu sederhana; kalau catatan sudah banyak/sering salah pilih,
  naikkan env atau (nanti) ganti ke pencarian vektor/embedding.

## Contoh isi
# Konfigurasi PPPoE MikroTik
- Cara buat profile PPPoE: /ppp profile add name=profile1 local-address=... remote-address=pool1
- Lupa password admin: boot → press 4 saat logo muncul → reset config tanpa kehilangan lisensi
