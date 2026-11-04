#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/src/unarc_helper.c"
OUT="$ROOT/libexec/unarc-helper.exe"

CC="${MINGW_CC:-}"
if [ -z "$CC" ] && command -v i686-w64-mingw32-gcc >/dev/null; then
    CC="$(command -v i686-w64-mingw32-gcc)"
fi
if [ -n "$CC" ]; then
    "$CC" -O2 -s -static "$SRC" -o "$OUT"
elif command -v x86_64-w64-mingw32-gcc >/dev/null; then
    echo "[ERRO] x86_64 MinGW nao serve: unarc.dll e PE32 (32-bit)." >&2
    exit 2
else
    echo "[ERRO] compilador MinGW PE32 nao encontrado." >&2
    echo "Defina MINGW_CC ou instale i686-w64-mingw32-gcc/LLVM-MinGW." >&2
    exit 2
fi

file "$OUT"
