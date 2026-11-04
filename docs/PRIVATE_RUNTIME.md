# Wine exigido pelo runtime

O pacote de publicação não inclui Wine. A pessoa usuária instala Wine para Linux
x86-64 ou disponibiliza Proton compatível antes de usar; `fitgirl doctor`
procura Wine/Proton no PATH, em locais usuais do Steam e em `FITGIRL_WINE_BIN`.
O programa usa Wine somente como ABI para DLLs, codecs e
pós-processamentos PE do repack. Nunca executa `setup.exe` e não configura Wine
como runner do jogo.

O launcher também procura runtimes Proton em locais usuais do Steam e aceita
`FITGIRL_WINE_BIN` como override explícito. Se nenhum executável válido iniciar,
a operação termina antes de solicitar o destino.

## Ambiente de desenvolvimento

O código de provisionamento de Wine privado continua disponível para
experimentos locais, mas o build de publicação não chama
`tools/prepare-bundled-wine.py` e não incorpora o arquivo binário. O arquivo
`.work/downloads/wine-11.14-fitgirl-amd64.tar.xz` é material local ignorado pelo
Git e não faz parte dos pacotes preparados.

## Destino e recursos

O destino sugerido é `~/Games/Nome` ou `Games/Nome` em outro dispositivo local
montado. Ele é criado somente após confirmação. Caminhos personalizados são
aceitos; prefixos Wine ficam no scratch, fora da árvore final.

O padrão deixa o sistema administrar recursos. Limites manuais são explicados
na interface: threads BZip3 afetam apenas esse codec; afinidade de CPUs aplica-se
ao backend. `MemoryHigh` é pressão suave; `MemoryMax` é rígido e pode encerrar
um codec.

QuickSFV x64 é detectado apenas em instalações existentes e não é necessário.
A validação MD5 é feita pelo verificador Linux interno. A release não contém o
QuickSFV porque não há concessão explícita de redistribuição documentada.

## Limites de plataforma

- Linux x86-64, glibc 2.38+, Python 3.12+, `libstdc++`, `libgcc_s` e Wine
  instalados no sistema.
- O artefato traz `innoextract`, `unarc`, `liblzma` e dependências não-base de
  `innoextract`, com inventário de hashes, fontes e avisos. O host ainda fornece
  glibc, `libstdc++` e `libgcc_s`.
- Debian 13, Ubuntu 24.04 e CachyOS rolling foram exercitados; demais
  distribuições precisam de validação própria.
- `fitgirl doctor` verifica os requisitos globais e os comandos necessários.
  A checagem não prova que todos os codecs específicos funcionarão.

Veja [`THIRD_PARTY.md`](THIRD_PARTY.md) para proveniência, licença e fontes dos
componentes redistribuídos.
