# Componentes de terceiros e distribuição

Esta página registra os binários usados pelo produto, a origem conferida e o
material de licença/código-fonte entregue no pacote de publicação. O arquivo
`dist/FitGirlInstaller-Linux-x86_64.zip` é o pacote de usuário; o código-fonte
correspondente está em `SOURCE-CODE.tar.gz` dentro dele e em
`third_party/source/` neste repositório.

## Binários incluídos

| Componente | Origem e identificação | Licença/aviso | Fonte correspondente |
|---|---|---|---|
| `innoextract` | Projeto dscharrer, commit `6e9e34ed0876014fdb46e684103ef8c3605e382e`; binário x86-64 em `libexec/innoextract`, SHA-256 `3bdd7896a38e3e99ab3661e56a2d8773e9c51c050070485d04eacdd77a691d03` | Zlib; aviso preservado | `third_party/source/innoextract/` |
| `unarc` | xredor/unarc, commit `adc333d6cdd76d72da254cc80d766fbbcc683c95`; binário x86-64, SHA-256 `20df4dc785b76dddb5d7265def469b515632ba114485f52cb7019a283e68c347`. O README upstream identifica a base FreeArc | GPL-2.0; texto da licença e avisos das fontes preservados | `third_party/source/unarc/`, com Makefile e licença GPL-2.0 |
| `unarc-helper.exe` | Código deste projeto em `src/unarc_helper.c`; PE32 i386. O build usa MinGW | Código do projeto; o PE importa APIs Windows/UCRT do Wine e não carrega runtime MinGW redistribuído | Fonte e receita em `src/unarc_helper.c` e `tools/build-unarc-helper.sh` |
| Bibliotecas carregadas por `innoextract` | Cópias dinâmicas em `libexec/`: Boost, zlib-ng-compat, bzip2 e zstd. O inventário/hash de cada arquivo está em `THIRD-PARTY-BINARIES.json`. `liblzma` não é copiada; o host deve fornecê-la | Boost Software License 1.0, licença Zlib, licença BSD de bzip2 e BSD/GPL-2.0 de zstd; avisos incluídos em `LICENSES/` | Boost é disponibilizado pelo upstream sob BSL-1.0; fontes e origens dos demais componentes constam em `LICENSES/THIRD_PARTY.md` |

As bibliotecas do sistema (`glibc`, loader ELF, `libstdc++`, `libgcc_s` e
`liblzma`) não são copiadas para o artefato; o sistema da pessoa usuária as
fornece. As outras dependências dinâmicas do `innoextract` são copiadas para o
runtime e inventariadas pelo build.

## Componentes deliberadamente fora da release

- **Wine FitGirl 11.14:** não é distribuído no pacote. A release usa Wine
  instalado pelo usuário; o projeto não inclui o arquivo binário cuja
  correspondência completa de fontes e patches não foi demonstrada.
- **QuickSFV 2.36:** não está no pacote. O site oficial identifica a versão, mas
  não concede termos explícitos de redistribuição. A validação do produto é
  feita pelo verificador Linux; QuickSFV é opcional para a pessoa usuária.
- DLLs de codecs, workers, redistribuíveis e payload de jogos: vêm do setup
  fornecido pelo usuário e não são armazenados neste repositório ou na release.
- innounp e pascalscript: ferramentas de análise locais, não redistribuídas.

## Como os fontes foram fixados

- `innoextract`: checkout upstream no commit registrado acima; o binário informa
  `1.10-dev + 6e9e34e`.
- `unarc`: checkout upstream no commit registrado acima. O próprio README diz
  que a implementação é completamente baseada em FreeArc. O repositório do fork
  não contém outro arquivo LICENSE; a licença GPL-2.0 declarada pelo projeto
  FreeArc e os avisos dos arquivos-fonte são preservados no snapshot entregue.
- Boost 1.92.0 e demais bibliotecas: versão, hash e licença do binário exato
  aparecem em `THIRD-PARTY-BINARIES.json`; seus textos de licença e páginas de
  origem ficam em `LICENSES/THIRD_PARTY.md`.

O source bundle preserva o código exato de `innoextract` e `unarc`, as licenças
e as receitas de build. `liblzma` é fornecida pelo sistema e não é distribuída
no artefato. Os binários do artefato são identificados por hashes. A licença não substitui
revisão jurídica, mas as permissões aplicáveis aos componentes mantidos e seus
avisos são incluídos na distribuição.

## Referências upstream

- [innoextract](https://github.com/dscharrer/innoextract)
- [unarc](https://github.com/xredor/unarc)
- [FreeArc no SourceForge (GPLv2)](https://sourceforge.net/projects/freearc/)
- [Boost Software License](https://www.boost.org/LICENSE_1_0.txt)
- [zlib-ng](https://github.com/zlib-ng/zlib-ng)
- [bzip2](https://sourceware.org/bzip2/)
- [zstd](https://github.com/facebook/zstd)
- [QuickSFV](https://www.quicksfv.org/)
