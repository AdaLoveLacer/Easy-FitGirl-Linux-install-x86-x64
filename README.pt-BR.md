# FitGirlWine

[English](README.md) | **Português (Brasil)**

Descompacta repacks da FitGirl no Linux, sem executar o `setup.exe`.

Você aponta para a pasta do repack e ela descompacta. Não há nada para
analisar, configurar, compilar ou instalar antes.

## Como usar

Baixe o projeto (ZIP do GitHub ou `git clone`) e descompacte onde quiser.
Depois, das duas formas abaixo, use a que preferir.

**Chamando de dentro da pasta do repack:**

```bash
cd "/caminho/do/repack"
~/FitGirlWine/fitgirl
```

**Ou passando a pasta do repack:**

```bash
~/FitGirlWine/fitgirl "/caminho/do/repack"
```

A pasta do repack é aquela onde está o `setup.exe`, junto dos volumes
`fg-01.bin`, `fg-02.bin` e assim por diante.

Em seguida a ferramenta pergunta o idioma e conduz o resto pelo terminal:
onde instalar, quais idiomas e opcionais incluir, e quanto de CPU e memória
usar. Enter aceita o padrão em todas as perguntas.

### Para digitar só `fitgirl`

Opcional, só para não repetir o caminho:

```bash
mkdir -p ~/.local/bin && ln -s ~/FitGirlWine/fitgirl ~/.local/bin/fitgirl
```

Se `~/.local/bin` já estiver no seu `PATH` — é o caso na maioria das
distribuições — a partir daí basta `fitgirl` em qualquer pasta.

## Requisitos

- Linux x86-64 com glibc 2.38 ou mais recente
- Python 3.12 ou mais recente
- Wine ou Proton instalado no sistema

Nada mais precisa ser compilado: os programas de extração já acompanham o
projeto em `libexec/`. Para conferir seu sistema:

```bash
./fitgirl doctor
```

## O que ela faz, e o que não faz

Ela extrai os arquivos do jogo e confere o resultado contra o
`_Redist/fitgirl.md5` que a própria FitGirl distribui dentro do repack. A
instalação é retomável: se parar no meio, rodar de novo continua de onde
estava.

Ela **não** executa o `setup.exe`, não cria atalhos, não mexe no registro do
Wine e não configura o jogo para iniciar. O trabalho dela termina nos
arquivos extraídos e verificados.

## Se um repack for recusado

A ferramenta lê a estrutura de etapas de dentro do próprio instalador. Alguns
instaladores fazem coisas que ela ainda não sabe reproduzir com segurança —
nesse caso ela para antes de escrever qualquer coisa no disco e diz o que
encontrou, apontando um relatório.

Isso é exceção, e não significa problema no seu sistema nem no download. Se
acontecer, o relatório indicado é o que ajuda a corrigir a ferramenta.

## Mapa do repositório

Para **usar**, só interessam estes:

| Caminho | O que é |
|---|---|
| `fitgirl` | o executável; é isto que você chama |
| `src/` | o código da ferramenta |
| `libexec/` | programas de extração que já vêm prontos |
| `manifests/` | planos de instalação já revisados |

O resto existe para **manter e auditar** a ferramenta, e não é necessário
para descompactar nada:

| Caminho | O que é |
|---|---|
| `tools/` | scripts de build, empacotamento e análise de instaladores |
| `tests/` | suíte automatizada |
| `docs/` | documentação de arquitetura, validação e pendências |
| `evidence/` | registros das validações feitas em repacks reais |
| `third_party/` | licenças e fontes correspondentes dos componentes de terceiros |
| `legacy/` | material antigo preservado |

A análise estática de instaladores (`tools/bootstrap-analysis.sh`,
[docs/ANALYSIS_TOOLS.md](docs/ANALYSIS_TOOLS.md), [docs/PLAN_AUDIT.md](docs/PLAN_AUDIT.md))
serve para **construir e corrigir a ferramenta**. Quem só quer descompactar um
repack não precisa de nada disso.

## Gerar o pacote standalone

Para manutenção, não para uso:

```bash
./tools/package-release.sh
```

O ZIP sai em `dist/FitGirlInstaller-Linux-x86_64.zip`, com o launcher, as
bibliotecas de extração, avisos de licença e os fontes correspondentes dos
componentes de terceiros. O Wine não é incluído.

## Licença

O material original do projeto é disponibilizado sob [0BSD](LICENSE). Os
componentes de terceiros mantêm suas próprias licenças; consulte os
[avisos de terceiros](docs/THIRD_PARTY.md).
