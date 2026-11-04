#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARCHIVE="$ROOT/third_party/source/xz/xz-5.8.4.tar.gz"
EXPECTED_SHA256=0014c7886930454fe8bd4228665b51af55eeae560ea135c9c4cd33f55b2591d9
BUILD_ROOT="$ROOT/.work/build/xz-5.8.4"
SOURCE="$BUILD_ROOT/source"
BUILD="$BUILD_ROOT/build"
PREFIX="$BUILD_ROOT/prefix"

echo "$EXPECTED_SHA256  $ARCHIVE" | sha256sum --check --status || {
  echo "Checksum inesperado para o source release do XZ Utils" >&2
  exit 1
}
rm -rf "$SOURCE" "$BUILD" "$PREFIX"
mkdir -p "$SOURCE" "$BUILD" "$PREFIX"
tar -xzf "$ARCHIVE" -C "$SOURCE" --strip-components=1
cmake -S "$SOURCE" -B "$BUILD" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DBUILD_SHARED_LIBS=ON \
  -DXZ_NLS=OFF \
  -DXZ_TOOL_XZ=OFF \
  -DXZ_TOOL_XZDEC=OFF \
  -DXZ_TOOL_LZMADEC=OFF \
  -DXZ_TOOL_LZMAINFO=OFF \
  -DXZ_DOC=OFF
cmake --build "$BUILD" --parallel
cmake --install "$BUILD"

LIBRARY="$(find "$PREFIX/lib" -maxdepth 1 -type f -name 'liblzma.so.*' -print -quit)"
if [[ -z "$LIBRARY" ]]; then
  echo "O build do XZ Utils não gerou liblzma compartilhada" >&2
  exit 1
fi
install -D -m 0755 "$LIBRARY" "$ROOT/.work/build/liblzma.so.5"
echo "Biblioteca criada: $ROOT/.work/build/liblzma.so.5"
