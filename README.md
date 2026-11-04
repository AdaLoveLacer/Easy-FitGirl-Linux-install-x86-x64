# FitGirl Installer para Linux

Instalador terminal que reconstrói o plano de um FitGirl Repack e extrai o jogo
sem executar a interface nem o fluxo original de `setup.exe`.

> Estado: funcional e validado em FM7, Mirage 7 e The Darkness 2, mas ainda não
> universal. Um setup cujo plano não possa ser provado é recusado.
>
> O pacote de publicação não inclui Wine: instale Wine para Linux x86-64 antes
> de usar. Os binários e bibliotecas abertos incluídos trazem licenças e fontes
> correspondentes no ZIP.

O gate final é objetivo: extração e pós-processamento concluídos, estrutura
esperada e manifestos FitGirl sem arquivos ausentes, hashes divergentes ou erro
CRC. Inicialização do jogo, jogabilidade, atalhos, registro e configuração de
runner estão fora do escopo.

## Uso

Existe somente um comando público:

```bash
fitgirl "/caminho/do/repack"
```

Também pode ser chamado diretamente a partir deste diretório:

```bash
./fitgirl "/caminho/do/repack"
```

O executável standalone intermediário fica em `dist/fitgirl`. O pacote de
usuário e publicação, com avisos, fontes correspondentes e checksum, fica em
`dist/FitGirlInstaller-Linux-x86_64.zip`. Gere ambos com:

```bash
./tools/package-release.sh
```

O build não baixa nem incorpora Wine. O launcher usa um Wine instalado pelo
usuário, encontra instalações Proton em locais usuais do Steam ou aceita
`FITGIRL_WINE_BIN`. Python com `tarfile.data_filter` (Python 3.12+), Linux
x86-64, glibc 2.38+ e bibliotecas hospedeiras compatíveis também são
necessários. `fitgirl doctor` verifica os requisitos globais.

O pacote inclui `THIRD_PARTY.md`, inventário com hashes, avisos de licença e
`SOURCE-CODE.tar.gz` com o código correspondente aos componentes redistribuídos.
QuickSFV e o Wine FitGirl privado não são incluídos.

O build recusa documentação operacional desatualizada. O estado canônico fica
em `status/project-status.json`; após alterá-lo, regenere e valide com:

```bash
./tools/sync-docs.py --write
./tools/sync-docs.py --check
```

`fitgirl doctor` mostra os requisitos detectados neste host e termina com erro
se Linux, arquitetura, glibc, Python, bibliotecas ou comandos necessários não
forem compatíveis.

Não são necessárias flags.

Na abertura, são exibidos o tamanho compactado disponível (setup e volumes,
incluindo opcionais) e, quando já registrada, a estimativa
`ExtraDiskSpaceRequired` do instalador. Ela não é uma medição exata do jogo
descompactado nem inclui necessariamente todos os intermediários/rollback.
Sem esse metadado, o menu informa que a estimativa não está disponível.
O resumo recalcula o compactado conforme os componentes escolhidos.

O menu terminal solicita:

- destino da instalação;
- componentes, idiomas e opcionais disponíveis;
- ajustes avançados de CPU e memória, somente se desejados;
- confirmação final para instalar ou retomar.

Scratch, prefixo Wine, journal e retomada são definidos automaticamente no
mesmo filesystem do destino. Repetir o comando e escolher o mesmo destino retoma
a primeira etapa que não foi confirmada.

O journal registra a ordem das etapas iniciadas e concluídas. Se essa ordem
divergir do plano selecionado, a instalação para antes da próxima etapa e grava
um diagnóstico em `scratch/reports/runtime-divergence-*.json`. A mensagem no
terminal indica a etapa esperada e a observada e pede que o usuário envie o
arquivo ao suporte. O diagnóstico omite caminhos locais, comandos e conteúdo dos
arquivos; ele não é enviado automaticamente.

O menu lista `~/Games/Nome do jogo` e uma pasta `Games` em cada disco local
montado distinto, mesmo que a pasta ainda não exista; ela é criada somente após
a confirmação da instalação. Uma opção adicional aceita o caminho completo.
Destinos sem permissão, somente leitura ou dentro de prefixos Wine são
recusados. O prefixo separado serve somente como ABI dos codecs, sem configurar
o jogo para jogar.

O modo automático de recursos é o recomendado. O menu avançado explica e
limita separadamente memória do SREP, threads do BZip3, afinidade global de CPU,
prioridade `nice`, `MemoryHigh` e `MemoryMax`. As faixas respeitam CPU disponível,
RAM livre, reserva para o sistema e limites cgroup herdados. `MemoryMax` continua
sendo um teto rígido capaz de encerrar o codec; a retomada reinicia a etapa.

QuickSFV x64 não solicita caminho no menu. Uma edição 2.36 x64 previamente
validada pode ser localizada automaticamente nas ferramentas privadas ou em
instalações existentes; somente o hash aprovado é reutilizado. A validação MD5
principal independe dele e é executada pelo verificador Linux interno.

Durante a extração, o terminal mostra progresso local e global ponderado,
atividade real de CPU/I/O, crescimento da saída e ETA quando há amostras
suficientes. Em arquivos sólidos, `entrada` mede o volume comprimido; depois de
99,5%, workers ainda ativos são mostrados como `PÓS-LEITURA` com ETA desconhecida,
sem prometer término. A barra global permanece limitada a 99,9% até a confirmação
final.

## O que o comando faz

1. localiza `setup.exe` no diretório informado;
2. identifica ou compila o plano a partir do ISS e `CompiledCode.bin`;
3. apresenta componentes disponíveis no menu;
4. valida os volumes antes de extraí-los;
5. executa a ordem e os pós-processamentos comprovados;
6. valida o resultado com `fitgirl.md5` e manifestos addon;
7. preserva journal e logs para retomada.

Wine é usado somente como ABI para `unarc.dll` e codecs Windows quando
necessário. O `setup.exe` não é executado.

## Organização

```text
fitgirl                     único executável público
src/fitgirl_installer/      implementação Python interna
src/native/                 fonte do helper PE32
libexec/                    backend e binários internos
manifests/                  cache/overrides de planos auditados
tests/                      testes automatizados
tools/                      ferramentas de desenvolvimento
docs/                       arquitetura, validações e troubleshooting
evidence/                   evidências empíricas locais
legacy/                     protótipo antigo que executava setup.exe
```

O arquivo `legacy/fitgirl-wine-installer.sh` não faz parte do produto atual. Ele
foi preservado apenas como histórico e executa a GUI original pelo Wine.

## Desenvolvimento

```bash
mkdir -p .work/tmp
export TMPDIR="$PWD/.work/tmp"
python3 -m unittest discover -s tests -v
./tools/sync-docs.py --check
python3 -m py_compile src/fitgirl_installer/*.py
bash -n libexec/fitgirl-extract
```

Requisitos canônicos: [`REQUIREMENTS.md`](REQUIREMENTS.md).

Documentação técnica:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/PLAN_AUDIT.md`](docs/PLAN_AUDIT.md)
- [`docs/ANALYSIS_TOOLS.md`](docs/ANALYSIS_TOOLS.md)
- [`docs/PRIVATE_RUNTIME.md`](docs/PRIVATE_RUNTIME.md)
- [`docs/INTEGRATION_POLICY.md`](docs/INTEGRATION_POLICY.md)
- [`docs/VALIDATION.md`](docs/VALIDATION.md)
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)
- [`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md)
- [`docs/PENDENCIAS.md`](docs/PENDENCIAS.md)
