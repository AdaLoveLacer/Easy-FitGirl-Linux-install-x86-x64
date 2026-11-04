# Avisos dos componentes redistribuídos

- **innoextract**: licença Zlib. Texto integral: `innoextract-zlib.txt`.
- **FreeArc / unarc**: o projeto xredor/unarc declara que a implementação é
  baseada em FreeArc. FreeArc é publicado sob GPL-2.0. Texto: `GPL-2.0.txt`.
  Os arquivos de origem mantêm cabeçalhos e avisos de componentes incorporados.
  O código GRZip incluído contém avisos LGPL; texto: `LGPL-2.1-only.txt`.
- **Boost**: Boost Software License 1.0; texto `Boost-1.0.txt`.
- **XZ Utils / liblzma 5.8.4**: o núcleo da biblioteca usa 0BSD. Outros arquivos
  do source release têm licenças distintas; os arquivos `COPYING` acompanham o
  source release completo incluído. O build distribui apenas a biblioteca
  compartilhada.
- **zlib-ng-compat**: licença Zlib; texto `zlib-ng.txt`.
- **bzip2**: licença BSD; texto `bzip2.txt`.
- **zstd**: distribuição sob BSD-3-Clause ou GPL-2.0-only; este produto usa os
  termos BSD-3-Clause, texto `zstd.txt`.
- **unarc-helper.exe**: código deste projeto, compilado contra APIs do sistema
  Windows/UCRT. Não contém DLLs de runtime MinGW redistribuídas.

O inventário `THIRD-PARTY-BINARIES.json` identifica o hash de cada payload ELF
ou PE incluído. `../THIRD_PARTY.md` aponta para os snapshots de origem e receitas.
