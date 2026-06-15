#!/bin/bash

# MikroFun Mikhmon Runner
# Jalankan Mikhmon di port 8080

PROJECT_DIR="/opt/mikrofun"
MIKHMON_DIR="$PROJECT_DIR/mikhmonv3"
PORT=8080

echo "Memulai Mikhmon v3 di port $PORT..."

if [ ! -d "$MIKHMON_DIR" ]; then
    echo "Error: Folder mikhmonv3 tidak ditemukan di $PROJECT_DIR"
    exit 1
fi

if ! command -v php &> /dev/null; then
    echo "Error: PHP belum terinstall. Silakan install dengan: apt install php-cli"
    exit 1
fi

# Jalankan di background
nohup php -S 0.0.0.0:$PORT -t "$MIKHMON_DIR" > /dev/null 2>&1 &

echo "Mikhmon berhasil dijalankan di background (port $PORT)."
echo "Silakan buka dashboard MikroFun dan akses menu Mikhmon."
