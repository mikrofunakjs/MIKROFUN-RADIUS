#!/bin/bash

# MikroFun Radius - Compile license_service.py ke license.so (Cython)
# Hanya dijalankan oleh admin saat release
# Hasil: web/license.so (binary)

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}   Compile license_service.py -> .so     ${NC}"
echo -e "${BLUE}=========================================${NC}"

cd "$(dirname "$0")"

# 1. Pastikan Cython terinstall
echo -e "${GREEN}[1/3] Checking Cython...${NC}"
if ! python3 -c "import Cython" 2>/dev/null; then
    echo "Installing Cython..."
    pip install cython
fi

# 2. Kompilasi
echo -e "${GREEN}[2/3] Compiling web/license_service.py...${NC}"
cythonize -i web/license_service.py

# 3. Verifikasi hasil
echo -e "${GREEN}[3/3] Verifying output...${NC}"
PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')")
SO_FILE=$(ls web/license_service.cpython-${PYTHON_VER}*.so 2>/dev/null | head -1)

if [ -n "$SO_FILE" ]; then
    echo -e "${GREEN}Output: $SO_FILE${NC}"
    echo ""
    echo "Python akan otomatis import .so ini karena nama sesuai konvensi."
    echo -e "${BLUE}=== DONE ===${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Commit file .so ke GitHub"
    echo "  2. web/license_service.py ada di .gitignore (source tidak ikut commit)"
    echo "  3. Clean __pycache__ :  find . -type d -name __pycache__ -exec rm -rf {} +"
    echo ""
    echo "NOTE: Jika Python version berubah (misal 3.10 -> 3.12),"
    echo "      harus rekompilasi ulang untuk versi baru."
else
    echo -e "${RED}ERROR: File .so tidak ditemukan!${NC}"
    echo "Cek apakah cythonize berhasil."
    ls -la web/license_service.* 2>/dev/null || echo "Tidak ada file hasil kompilasi."
    exit 1
fi
