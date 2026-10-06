#!/usr/bin/env bash
# Compila Comandia.exe (lanzador para Windows) desde Linux con MinGW-w64:
#   sudo apt install gcc-mingw-w64-x86-64 && windows/build.sh
set -euo pipefail
cd "$(dirname "$0")"
x86_64-w64-mingw32-windres comandia.rc -O coff -o comandia-res.o
x86_64-w64-mingw32-gcc -O2 -s -municode -mwindows -o ../Comandia.exe launcher.c comandia-res.o -lws2_32 -liphlpapi -lshell32
rm -f comandia-res.o
echo "Listo: Comandia.exe"
