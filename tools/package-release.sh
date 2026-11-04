#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/tools/sync-docs.py" --check
"$ROOT/tools/build-standalone.sh"

RELEASE_ROOT="$ROOT/.work/release-package"
PACKAGE="$RELEASE_ROOT/FitGirlInstaller-Linux-x86_64"
SOURCE_ARCHIVE="$PACKAGE/SOURCE-CODE.tar.gz"
rm -rf "$RELEASE_ROOT"
mkdir -p "$PACKAGE/LICENSES"
cp "$ROOT/dist/fitgirl" "$PACKAGE/fitgirl"
cp "$ROOT/dist/THIRD-PARTY-BINARIES.json" "$PACKAGE/THIRD-PARTY-BINARIES.json"
cp "$ROOT/docs/THIRD_PARTY.md" "$PACKAGE/THIRD_PARTY.md"
cp "$ROOT/third_party/licenses/"* "$PACKAGE/LICENSES/"
cp "$ROOT/third_party/components.json" "$PACKAGE/LICENSES/components.json"

SOURCE_STAGE="$RELEASE_ROOT/source"
mkdir -p "$SOURCE_STAGE"
cp -a "$ROOT/third_party/source" "$SOURCE_STAGE/"
cp -a "$ROOT/third_party/licenses" "$SOURCE_STAGE/"
cp "$ROOT/third_party/components.json" "$ROOT/third_party/BUILDING.md" "$SOURCE_STAGE/"
cp "$ROOT/src/unarc_helper.c" "$SOURCE_STAGE/"
cp "$ROOT/tools/build-unarc-helper.sh" "$SOURCE_STAGE/"
tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner \
  -C "$SOURCE_STAGE" -cf - . | gzip -n -9 > "$SOURCE_ARCHIVE"

cat > "$PACKAGE/LEIA-ME.txt" <<'TXT'
FitGirl Installer para Linux — pacote de publicação

Requisitos: Linux x86-64, glibc 2.38 ou superior, Python 3.12 ou superior,
Wine compatível instalado no sistema e as bibliotecas-base do Linux descritas
em THIRD_PARTY.md. O Wine não é incluído no pacote.

Uso: ./fitgirl "/caminho/do/repack"
O setup.exe não é executado. Planos não comprovados são recusados.

O diretório LICENSES e THIRD_PARTY.md identificam binários, bibliotecas,
licenças, avisos e origens. SOURCE-CODE.tar.gz contém os fontes correspondentes
aos componentes de terceiros redistribuídos e suas receitas de build.
QuickSFV e Wine FitGirl não são incluídos.
TXT

(
  cd "$PACKAGE"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
  find . -type f -exec touch -t 198001010000 {} +
  mapfile -d '' FILES < <(find . -type f -print0 | sort -z)
  rm -f "$ROOT/dist/FitGirlInstaller-Linux-x86_64.zip"
  zip -X -9 -q "$ROOT/dist/FitGirlInstaller-Linux-x86_64.zip" "${FILES[@]}"
)
sha256sum "$ROOT/dist/FitGirlInstaller-Linux-x86_64.zip" > "$ROOT/dist/FitGirlInstaller-Linux-x86_64.zip.sha256"
echo "Pacote criado: $ROOT/dist/FitGirlInstaller-Linux-x86_64.zip"
cat "$ROOT/dist/FitGirlInstaller-Linux-x86_64.zip.sha256"
