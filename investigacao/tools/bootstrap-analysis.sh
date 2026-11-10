#!/usr/bin/env bash
# Local analysis dependencies only; never added to the redistributable runtime.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/.work/analysis-bootstrap"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/fitgirl-installer/tools"
REV='5b9164cb8b563506695f7f62b17f002d6aa2cac4'
SRC="$WORK/pascalscript-$REV"
mkdir -p "$WORK/tmp" "$DATA"
export TMPDIR="$WORK/tmp"
if [ ! -e "$SRC" ]; then
    git clone https://github.com/ATRAPSLLC/pascalscript-rs.git "$SRC"
    git -C "$SRC" checkout --detach "$REV"
fi
[ "$(git -C "$SRC" rev-parse HEAD)" = "$REV" ] || {
    echo 'Fonte existente diverge do commit fixado; não será sobrescrito.' >&2
    exit 1
}
if git -C "$SRC" apply --check "$ROOT/investigacao/tools/pascalscript-dll-function-names.patch"; then
    git -C "$SRC" apply "$ROOT/investigacao/tools/pascalscript-dll-function-names.patch"
else
    git -C "$SRC" apply --reverse --check "$ROOT/investigacao/tools/pascalscript-dll-function-names.patch"
fi
cp "$ROOT/investigacao/tools/pascalscript-cli.rs" "$SRC/src/main.rs"
cargo generate-lockfile --offline --manifest-path "$SRC/Cargo.toml"
cargo test --locked --manifest-path "$SRC/Cargo.toml"
cargo build --release --locked --manifest-path "$SRC/Cargo.toml"
ARCHIVE="$WORK/innounp050.rar"
if [ ! -f "$ARCHIVE" ]; then
    curl --fail --location --connect-timeout 15 --max-time 120 \
        https://sourceforge.net/projects/innounp/files/latest/download -o "$ARCHIVE"
fi
echo "1d8837540ccc15d98245a1c73fd08f404b2a7bdfe7dc9bed2fdece818ff6df67  $ARCHIVE" | sha256sum -c -
mkdir -p "$WORK/innounp"
7z x -y "-o$WORK/innounp" "$ARCHIVE"
echo "9b72ad9f93d167652a0e2bf3921abdfd3e6747c5e718461a2e58b9dfacd31f4c  $WORK/innounp/innounp.exe" | sha256sum -c -
install -m 755 "$SRC/target/release/pascalscript" "$DATA/pascalscript"
install -m 644 "$WORK/innounp/innounp.exe" "$DATA/innounp.exe"
sha256sum "$DATA/pascalscript" "$DATA/innounp.exe" > "$DATA/SHA256SUMS"
echo "Ferramentas persistentes: $DATA"
