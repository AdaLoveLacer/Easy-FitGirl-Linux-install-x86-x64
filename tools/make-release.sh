#!/usr/bin/env bash
# Publica uma release no GitHub a partir do estado atual do repositório.
#
#   ./tools/make-release.sh v0.1.0
#   ./tools/make-release.sh v0.1.0 --dry-run    # prepara tudo, não publica
#
# Faz, nesta ordem: confere o repositório, roda a suíte, reconstrói o arquivo
# único e o ZIP, cria a tag e publica a release com os três ativos. Para em
# qualquer falha, antes de criar tag ou release.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSAO="${1:-}"
DRY_RUN=0
[[ "${2:-}" == "--dry-run" ]] && DRY_RUN=1

if [[ -z "$VERSAO" ]]; then
  echo "uso: $0 vX.Y.Z [--dry-run]" >&2
  exit 2
fi
if [[ ! "$VERSAO" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "versão deve ser vX.Y.Z, recebi: $VERSAO" >&2
  exit 2
fi

passo() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

passo "Conferindo o repositório"
if [[ -n "$(git status --porcelain)" ]]; then
  echo "há mudanças não commitadas; a release precisa sair de uma árvore limpa" >&2
  git status --short >&2
  exit 1
fi
if git rev-parse -q --verify "refs/tags/$VERSAO" >/dev/null; then
  echo "a tag $VERSAO já existe" >&2
  exit 1
fi
RAMO="$(git rev-parse --abbrev-ref HEAD)"
echo "ramo $RAMO em $(git rev-parse --short HEAD)"
./tools/sync-docs.py --check

passo "Rodando a suíte automatizada"
mkdir -p "$ROOT/.work/tmp"
TMPDIR="$ROOT/.work/tmp" FITGIRL_LANGUAGE=pt python3 -m unittest discover -s tests

passo "Construindo o arquivo único e o pacote"
./tools/package-release.sh

ARQUIVO_UNICO="$ROOT/dist/fitgirl"
PACOTE="$ROOT/dist/FitGirlInstaller-Linux-x86_64.zip"
SOMAS="$ROOT/dist/SHA256SUMS"
for alvo in "$ARQUIVO_UNICO" "$PACOTE"; do
  [[ -f "$alvo" ]] || { echo "ativo ausente: $alvo" >&2; exit 1; }
done
(cd "$ROOT/dist" && sha256sum fitgirl FitGirlInstaller-Linux-x86_64.zip > SHA256SUMS)

passo "Conferindo o arquivo único isolado"
# Um autoextraível quebrado só aparece quando roda fora do repositório, com
# cache vazio: é assim que o usuário o recebe.
ENSAIO="$(mktemp -d "$ROOT/.work/release-check.XXXXXX")"
trap 'rm -rf "$ENSAIO"' EXIT
cp "$ARQUIVO_UNICO" "$ENSAIO/fitgirl"
XDG_CACHE_HOME="$ENSAIO/cache" FITGIRL_LANGUAGE=pt "$ENSAIO/fitgirl" doctor >/dev/null
XDG_CACHE_HOME="$ENSAIO/cache" FITGIRL_LANGUAGE=pt "$ENSAIO/fitgirl" licenses >/dev/null
echo "doctor e licenses responderam a partir do arquivo único"

TAMANHO="$(du -h "$ARQUIVO_UNICO" | cut -f1)"
SOMA_UNICO="$(sha256sum "$ARQUIVO_UNICO" | cut -d' ' -f1)"
NOTAS="$ROOT/.work/release-notes-$VERSAO.md"
cat > "$NOTAS" <<NOTA
Descompacta repacks da FitGirl no Linux, sem executar o \`setup.exe\`.

## Como usar

Baixe o \`fitgirl\` abaixo, dê permissão de execução e chame de dentro da
pasta do repack — aquela onde está o \`setup.exe\` com os volumes \`fg-01.bin\`:

\`\`\`bash
chmod +x fitgirl
cd "/caminho/do/repack"
/caminho/do/fitgirl
\`\`\`

Ou passe a pasta: \`./fitgirl "/caminho/do/repack"\`

Requer Linux x86-64 com glibc 2.38+, Python 3.12+ e Wine ou Proton
instalado. Use \`./fitgirl doctor\` para conferir o sistema.

## Ativos

| Arquivo | Para quê |
|---|---|
| \`fitgirl\` | **o que você quer**: arquivo único, $TAMANHO, autossuficiente |
| \`FitGirlInstaller-Linux-x86_64.zip\` | o mesmo, com avisos de licença e fontes de terceiros em arquivos separados |
| \`SHA256SUMS\` | somas para verificação |

\`\`\`
$SOMA_UNICO  fitgirl
\`\`\`

O arquivo único traz os avisos de licença embutidos: \`./fitgirl licenses\`.

## Reprodutibilidade

O build é determinístico (\`tar --sort=name --mtime=@0 --owner=0\`, \`gzip -n\`).
Rodando \`./tools/package-release.sh\` a partir desta tag, o SHA-256 do
\`fitgirl\` publicado deve ser idêntico ao acima.
NOTA

passo "Resumo"
cat "$SOMAS"
echo "notas em $NOTAS"

if (( DRY_RUN )); then
  passo "--dry-run: nada foi publicado"
  echo "para publicar: $0 $VERSAO"
  exit 0
fi

command -v gh >/dev/null || { echo "gh não encontrado; instale o GitHub CLI" >&2; exit 1; }

passo "Criando a tag $VERSAO"
git tag -a "$VERSAO" -m "FitGirlWine $VERSAO"
git push origin "$VERSAO"

passo "Publicando a release"
gh release create "$VERSAO" \
  "$ARQUIVO_UNICO" "$PACOTE" "$SOMAS" \
  --title "FitGirlWine $VERSAO" --notes-file "$NOTAS"

passo "Publicada"
gh release view "$VERSAO" --json url --jq .url
