# FitGirlWine

[English](README.md) | **Português (Brasil)**

FitGirlWine é uma ferramenta de linha de comando para Linux que extrai repacks FitGirl compatíveis sem executar o `setup.exe`. Ela aceita somente repacks com plano de instalação auditado, ou cujo plano gerado automaticamente passa por todas as provas estáticas contra uma versão já analisada da ISDone.dll; planos desconhecidos ou sem prova são recusados, e o MD5 do próprio repack confere toda instalação.

## Início rápido

```bash
./fitgirl "/caminho/do/repack"
```

Escolha o idioma da interface quando solicitado. Para execução automatizada, defina `FITGIRL_LANGUAGE=pt` ou `FITGIRL_LANGUAGE=en`.

## Requisitos

- Linux x86-64 com glibc 2.38 ou mais recente
- Python 3.12 ou mais recente
- Wine ou Proton compatível instalado no sistema
- Bibliotecas de sistema compatíveis e ferramentas padrão de linha de comando do Linux

Execute `./fitgirl doctor` para conferir os requisitos do sistema atual.

## Gerar o pacote standalone

```bash
./tools/package-release.sh
```

O ZIP será criado em `dist/FitGirlInstaller-Linux-x86_64.zip`. Ele inclui o launcher, as bibliotecas de extração necessárias, avisos de licença e os fontes correspondentes dos componentes de terceiros. O Wine não é incluído.

## Licença

O material original do projeto é disponibilizado sob [0BSD](LICENSE). Os componentes de terceiros mantêm suas próprias licenças; consulte os [avisos de terceiros](docs/THIRD_PARTY.md).
