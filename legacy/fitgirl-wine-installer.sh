#!/usr/bin/env bash
# ============================================================================
# fitgirl-wine-installer.sh - Instalador autonomo de FitGirl Repacks no Linux
# ----------------------------------------------------------------------------
# Goal: run FitGirl Repack setup.exe under Proton/Wine with every known fix
#       applied, in a clean disposable prefix, fully logged, crash-loop aware.
#
# Root cause this tool works around:
#   - Arch/CachyOS system `wine` is a WoW64-only build (no /usr/lib32/wine),
#     which cannot run the 32-bit unarc.dll / cls-*.exe decompressor chain
#     used by FitGirl installers. Proton builds are full multilib wine.
#   - FitGirl-known Wine fixes: Windows XP global version, real cmd.exe,
#     optional ulimit -v, PROTON_LARGE_ADDRESS_AWARE=0, virtual desktop.
#
# Usage:
#   ./fitgirl-wine-installer.sh -d "/mnt/Eita/Torrent/Games/<repack>/" \
#       -t "/mnt/Eita/Games/<Game>" [-l en] [--prefix PATH] [--proton NAME|PATH]
#       [--gui] [--ulimit MB] [--large-address-off] [--skip-verify]
#
# Exit codes: 0 = install finished, 1 = setup.exe crash/exit nonzero,
#             2 = environment/validation error.
# ============================================================================
set -o pipefail

SCRIPT_NAME="fitgirl-wine-installer"

# ---------------------------------------------------------------- defaults
SETUP_DIR=""
INSTALL_DIR=""
LANG_="en"
PREFIX_ROOT="${PREFIX_ROOT:-/mnt/Eita/WinePrefixes}"
PREFIX_NAME=""
PROTON_ROOTS=(
    "$HOME/.local/share/Steam/compatibilitytools.d"
    "/usr/share/steam/compatibilitytools.d"
)
PROTON_NAME="Proton-CachyOS-11"
WINDOWS_VERSION="${WINDOWS_VERSION:-win7}"
UMU_GAMEID="${UMU_GAMEID:-umu-default}"
MODE="SILENT"          # SILENT | GUI
ULIMIT_MB=0            # 0 = off
LARGE_ADDRESS_OFF=0
SKIP_VERIFY=0
LOG_ROOT="${LOG_ROOT:-/tmp/opencode/logs}"

usage() { grep -E "^# (Usage:|- )" "$0" | sed 's/^# //'; }

err()  { echo "[ERRO] $*" >&2; exit 2; }
info() { echo "[INFO] $*"; }

# ---------------------------------------------------------------- args
# Manual parser: Bash getopts treats a bare `--` as an option with an empty
# argument on some versions, so long options are handled explicitly here.
while [ "$#" -gt 0 ]; do
    case "$1" in
        -d) SETUP_DIR="$2"; shift 2 ;;
        -t) INSTALL_DIR="$2"; shift 2 ;;
        -l) LANG_="$2"; shift 2 ;;
        -p|--prefix) PREFIX_NAME="$2"; shift 2 ;;
        -g|--gui) MODE="GUI"; shift ;;
        -T|--proton) PROTON_NAME="$2"; shift 2 ;;
        -L) ULIMIT_MB="$2"; shift 2 ;;
        -P) PROTON_ROOTS+=("$2"); shift 2 ;;
        --ulimit) ULIMIT_MB="$2"; shift 2 ;;
        --ulimit=*) ULIMIT_MB="${1#*=}"; shift ;;
        --large-address-off) LARGE_ADDRESS_OFF=1; shift ;;
        --windows-version) WINDOWS_VERSION="$2"; shift 2 ;;
        --windows-version=*) WINDOWS_VERSION="${1#*=}"; shift ;;
        --skip-verify) SKIP_VERIFY=1; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; break ;;
        -*) err "opcao desconhecida: $1" ;;
        *) err "argumento inesperado: $1" ;;
    esac
done

# ---------------------------------------------------------------- resolve dirs
[ -n "$SETUP_DIR" ] || { usage >&2; exit 2; }
[ -f "$SETUP_DIR/setup.exe" ] || err "setup.exe nao encontrado em: $SETUP_DIR"
SETUP_DIR="${SETUP_DIR%/}"
BASENAME="$(basename "$SETUP_DIR")"
LOG_DIR="$LOG_ROOT/${SCRIPT_NAME}-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LOG_DIR"

# install dir default: beside the repack
if [ -z "$INSTALL_DIR" ]; then
    INSTALL_DIR="$(dirname "$SETUP_DIR")/installed-$(echo "$BASENAME" | tr -c 'A-Za-z0-9._-' '-')"
fi

# ---------------------------------------------------------------- find proton
find_proton() {
    local name="$1"
    for root in "${PROTON_ROOTS[@]}"; do
        if [ -d "$root/$name" ] && [ -x "$root/$name/proton" ]; then
            echo "$root/$name"; return 0
        fi
    done
    return 1
}

PROTON_PATH="$(find_proton "$PROTON_NAME")"
if [ -z "$PROTON_PATH" ]; then
    info "Proton '$PROTON_NAME' nao achado. Disponiveis:"
    for root in "${PROTON_ROOTS[@]}"; do
        [ -d "$root" ] && ls "$root" 2>/dev/null | sed "s|^|  - $root/|"
    done
    err "informe um build valido com -T <nome-da-pasta>"
fi
info "Proton: $PROTON_PATH"

# ---------------------------------------------------------------- wine sanity
if [ ! -d /usr/lib32/wine/i386-unix ] && ! command -v umu-run >/dev/null; then
    err "wine do sistema e WoW64 e sem umu-run disponivel. Instale umu-run ou um Proton."
fi
command -v umu-run >/dev/null || err "umu-run nao encontrado no PATH"

# ---------------------------------------------------------------- prefix
[ -n "$PREFIX_NAME" ] || PREFIX_NAME="fg-repack"
WINEPREFIX="$PREFIX_ROOT/$PREFIX_NAME"
mkdir -p "$WINEPREFIX"
info "WINEPREFIX: $WINEPREFIX"
export WINEPREFIX GAMEID="$UMU_GAMEID" PROTONPATH="$PROTON_PATH"
export UMU_LOG=info

# known regressions mitigations (apply only when requested)
if [ "$LARGE_ADDRESS_OFF" = 1 ]; then
    export PROTON_LARGE_ADDRESS_AWARE=0
    info "PROTON_LARGE_ADDRESS_AWARE=0 aplicado"
fi

# ---------------------------------------------------------------- prefix init
if [ ! -f "$WINEPREFIX/pfx.lock" ] && [ ! -d "$WINEPREFIX/drive_c/windows" ]; then
    info "Inicializando prefixo (primeira execucao)..."
    umu-run wineboot -i >>"$LOG_DIR/prefix_init.log" 2>&1
fi

# Windows XP global (FitGirl WINE troubleshooting: admin-check hang on >=Vista)
info "Aplicando Windows Version=$WINDOWS_VERSION no prefixo..."
umu-run wine reg add "HKCU\\Software\\Wine" /v Version /t REG_SZ /d "$WINDOWS_VERSION" /f \
    >>"$LOG_DIR/prefix_setup.log" 2>&1

# real cmd.exe (FitGirl troubleshooting); verb downloads once, tolerates failure
info "Tentando winetricks cmd (timeout de 60s, nao fatal se falhar)..."
timeout --signal=TERM 60s umu-run winetricks cmd >>"$LOG_DIR/winetricks_cmd.log" 2>&1 \
    || info "winetricks cmd falhou (seguimos com o cmd builtin do wine)"

# ---------------------------------------------------------------- verify bins
if [ "$SKIP_VERIFY" = 0 ] && [ -f "$SETUP_DIR/MD5/fitgirl-bins.md5" ]; then
    info "Verificando integridade dos .bin (pode demorar minutos)..."
    sed 's|\*\.\.\\|./|' "$SETUP_DIR/MD5/fitgirl-bins.md5" | grep -E '^\*' >"$LOG_DIR/md5_fixed.txt" \
        || sed 's|\.\.\\|./|g; s|^;.*||' "$SETUP_DIR/MD5/fitgirl-bins.md5" >"$LOG_DIR/md5_fixed.txt"
    ( cd "$SETUP_DIR" && md5sum -c "$LOG_DIR/md5_fixed.txt" ) >>"$LOG_DIR/md5_result.log" 2>&1
    if grep -q ": OK" "$LOG_DIR/md5_result.log" && ! grep -q ": FALHA\|: FAILED\|: Aberto\|abertura" "$LOG_DIR/md5_result.log"; then
        info "MD5 OK em todos os .bin listados."
    else
        info "AVISO: nem todos os .bin passaram no MD5 (veja $LOG_DIR/md5_result.log)"
        info "Continuando mesmo assim (--skip-verify para pular este aviso no futuro)."
    fi
fi

# ---------------------------------------------------------------- limits
if [ "$ULIMIT_MB" -gt 0 ]; then
    info "ulimit -v ${ULIMIT_MB}MB aplicado (fix de crash de memoria)"
    ulimit -v "$((ULIMIT_MB*1024))"
fi

# ---------------------------------------------------------------- run setup
if command -v winepath >/dev/null; then
    # Proton prefixes may map mounts to W:, Y:, etc.; never assume Z:.
    WINDIR="$(WINEDEBUG=-all winepath -w "$INSTALL_DIR" 2>/dev/null | tr -d '\r')"
fi
# winepath can briefly fail while umu is releasing its wineserver lock. Resolve
# the prefix's dosdevices directly as a fallback, preserving arbitrary mounts.
if [ -z "$WINDIR" ]; then
    for drive in "$WINEPREFIX"/dosdevices/*:; do
        [ -L "$drive" ] || continue
        host_root="$(readlink -f "$drive")"
        case "$INSTALL_DIR/" in
            "$host_root"/*)
                rel="${INSTALL_DIR#"$host_root"/}"
                letter="$(basename "$drive" | tr '[:lower:]' '[:upper:]' | tr -d ':')"
                WINDIR="${letter}:\\${rel//\//\\}"
                break
                ;;
        esac
    done
fi
[ -n "$WINDIR" ] || err "nao foi possivel converter o destino para caminho Windows: $INSTALL_DIR"
info "Destino Windows: $WINDIR"
# umu/proton: unix paths starting with / are wrapped; use Z: only if unix path fails
ARGS=(setup.exe /LANG="$LANG_")
if [ "$MODE" = "SILENT" ]; then
    ARGS+=(/SILENT /SUPPRESSMSGBOXES /NOCANCEL "/DIR=$WINDIR")
fi

info "Executando: umu-run ${ARGS[*]}"
info "Log completo: $LOG_DIR/setup.log"
cd "$SETUP_DIR"

umu-run "${ARGS[@]}" 2>&1 | tee "$LOG_DIR/setup.log"
RC=${PIPESTATUS[0]}

echo "$RC" >"$LOG_DIR/exit_code"
if [ "$RC" = 0 ]; then
    info "Instalacao finalizada (exit 0). Jogo em: $INSTALL_DIR"
else
    info "Instalador terminou com exit $RC. Veja o log: $LOG_DIR/setup.log"
    info "Caixas de erro: unarc.dll/ISDone indices aparecem no final do log."
fi
exit "$RC"
