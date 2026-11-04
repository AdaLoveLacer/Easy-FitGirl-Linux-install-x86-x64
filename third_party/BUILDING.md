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
código-fonte no source release oficial XZ Utils 5.8.4 em
`source/xz/xz-5.8.4.tar.gz`. Execute `tools/build-liblzma.sh` para validar o
SHA-256 e construir a biblioteca compartilhada incluída no pacote. Os avisos
de licença do source release são entregues em `licenses/` e no arquivo-fonte.
