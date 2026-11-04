# Fontes correspondentes e receitas de build

Este diretório contém snapshots de fonte e avisos correspondentes aos binários
redistribuídos. A versão ELF de `innoextract` foi compilada do commit travado em
`components.json`; requer CMake, Boost, xz/liblzma, zlib, bzip2 e zstd:

```sh
cmake -S third_party/source/innoextract -B .work/build/innoextract \
  -DCMAKE_BUILD_TYPE=Release -DUSE_SYSTEM_BOOST=ON
cmake --build .work/build/innoextract --parallel
```

O backend `unarc` tem a receita original em
`third_party/source/unarc/Makefile`. Para reproduzir com GCC/G++:

```sh
make -C third_party/source/unarc clean
make -C third_party/source/unarc CXX=g++
```

O helper PE32 tem código e receita em `src/unarc_helper.c` e
`tools/build-unarc-helper.sh`; o build requer compilador MinGW-w64 i686.

As versões binárias incluídas no pacote e seus hashes exatos aparecem em
`THIRD-PARTY-BINARIES.json`. Bibliotecas Boost, bzip2, zlib-ng-compat e zstd têm
licenças permissivas; seus avisos estão em `licenses/`. O binário `liblzma` tem
código fornecido pelo sistema hospedeiro e não é redistribuído pelo pacote.
