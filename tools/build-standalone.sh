#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/tools/sync-docs.py" --check
mkdir -p "$ROOT/.work/build"
BUILD_DIR="$(mktemp -d "$ROOT/.work/build/fitgirl-build.XXXXXX")"
STAGE="$BUILD_DIR/runtime"
ARCHIVE="$BUILD_DIR/runtime.tar.gz"
OUTPUT="$BUILD_DIR/fitgirl"
FINAL_OUTPUT="$ROOT/dist/fitgirl"
trap 'rm -rf "$BUILD_DIR"' EXIT

mkdir -p "$STAGE/src" "$STAGE/libexec" "$ROOT/dist"
cp "$ROOT/fitgirl" "$STAGE/fitgirl"
cp -a "$ROOT/src/fitgirl_installer" "$STAGE/src/"
cp -a "$ROOT/manifests" "$STAGE/"
cp "$ROOT/libexec/fitgirl-extract" "$STAGE/libexec/fitgirl-extract"
cp "$ROOT/libexec/innoextract" "$STAGE/libexec/innoextract"
python3 "$ROOT/tools/copy-innoextract-libs.py" \
  --binary "$ROOT/libexec/innoextract" --destination "$STAGE/libexec"
"$ROOT/tools/build-liblzma.sh"
install -m 0755 "$ROOT/.work/build/liblzma.so.5" "$STAGE/libexec/liblzma.so.5"
LZMA_RESOLUTION="$(LD_LIBRARY_PATH="$STAGE/libexec" ldd "$STAGE/libexec/innoextract" \
  | awk '/liblzma\.so\.5 =>/ { print $3; exit }')"
if [[ "$LZMA_RESOLUTION" != "$STAGE/libexec/liblzma.so.5" ]]; then
  echo "innoextract não está usando a liblzma incluída: ${LZMA_RESOLUTION:-ausente}" >&2
  exit 1
fi
cp "$ROOT/libexec/unarc" "$STAGE/libexec/unarc"
cp "$ROOT/libexec/unarc-helper.exe" "$STAGE/libexec/unarc-helper.exe"
python3 "$ROOT/tools/write-third-party-manifest.py" \
  "$STAGE" "$STAGE/THIRD-PARTY-BINARIES.json"
# Quem baixa apenas o arquivo único também precisa dos avisos: sem isto, só
# o ZIP entregaria LICENSE e LICENSES/. Exibidos por `fitgirl licenses`.
mkdir -p "$STAGE/LICENSES"
cp "$ROOT/LICENSE" "$STAGE/LICENSE"
cp "$ROOT/docs/THIRD_PARTY.md" "$STAGE/LICENSES/THIRD_PARTY.md"
cp "$ROOT/third_party/licenses/"* "$STAGE/LICENSES/"
cp "$ROOT/third_party/components.json" "$STAGE/LICENSES/components.json"
find "$STAGE" -type d -name __pycache__ -prune -exec rm -rf {} +
chmod +x "$STAGE/fitgirl" "$STAGE/libexec/fitgirl-extract" \
  "$STAGE/libexec/innoextract" "$STAGE/libexec/unarc" \
  "$STAGE/libexec/unarc-helper.exe"

tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner \
  -C "$STAGE" -cf - . | gzip -n -9 > "$ARCHIVE"
RUNTIME_ID="$(sha256sum "$ARCHIVE" | cut -c1-16)"

cat > "$OUTPUT" <<EOF
#!/usr/bin/env bash
set -euo pipefail
SELF="\$(readlink -f "\$0")"
CACHE_ROOT="\${XDG_CACHE_HOME:-\$HOME/.cache}/fitgirl-installer/runtime"
RUNTIME="\$CACHE_ROOT/$RUNTIME_ID"
MARKER='__FITGIRL_ARCHIVE_BELOW__'
if [ ! -x "\$RUNTIME/fitgirl" ]; then
  mkdir -p "\$CACHE_ROOT"
  TEMP="\$(mktemp -d "\$CACHE_ROOT/.unpack.XXXXXX")"
  cleanup() { rm -rf "\$TEMP"; }
  trap cleanup EXIT
  LINE="\$(awk -v marker="\$MARKER" '\$0 == marker { print NR + 1; exit }' "\$SELF")"
  tail -n "+\$LINE" "\$SELF" | tar -xzf - -C "\$TEMP"
  chmod +x "\$TEMP/fitgirl" "\$TEMP/libexec/fitgirl-extract" \
    "\$TEMP/libexec/innoextract" "\$TEMP/libexec/unarc"
  mv "\$TEMP" "\$RUNTIME"
  trap - EXIT
fi
LD_LIBRARY_PATH="\$RUNTIME/libexec\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export LD_LIBRARY_PATH
exec "\$RUNTIME/fitgirl" "\$@"
exit 127
__FITGIRL_ARCHIVE_BELOW__
EOF
cat "$ARCHIVE" >> "$OUTPUT"
chmod +x "$OUTPUT"
mv -f "$OUTPUT" "$FINAL_OUTPUT"
(cd "$ROOT/dist" && sha256sum fitgirl > SHA256SUMS)
cp "$STAGE/THIRD-PARTY-BINARIES.json" "$ROOT/dist/THIRD-PARTY-BINARIES.json"
echo "Criado: $FINAL_OUTPUT"
cat "$ROOT/dist/SHA256SUMS"
