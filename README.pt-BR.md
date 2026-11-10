# FitGirlWine

[English](README.md) | **Português (Brasil)**

Descompacta repacks da FitGirl no Linux, sem executar o `setup.exe`.

Você aponta para a pasta do repack e ela descompacta. Não há nada para
analisar, configurar, compilar ou instalar antes.

## Como usar — do zero

**1. Instale o Wine** pela sua distribuição. Você também precisa de Python
3.12 ou mais novo, que já vem na maioria das distribuições atuais.

**2. Baixe o projeto.** Pelo ZIP do GitHub, ou:

```bash
git clone https://github.com/AdaLoveLacer/Easy-FitGirl-Linux-install-x86-x64.git ~/FitGirlWine
```

O `~/FitGirlWine` no fim é só para a pasta ter um nome curto; sem ele, o
clone cria uma pasta com o nome longo do repositório.

> Nos comandos abaixo, **`~/FitGirlWine` é a pasta onde você baixou o
> projeto**. Se você já tem o projeto em outro lugar, troque por esse
> caminho — por exemplo `~/Documentos/FitGirlWine/fitgirl`.

**3. Entre na pasta do repack** — aquela onde está o `setup.exe` junto dos
volumes `fg-01.bin`, `fg-02.bin` e assim por diante:

```bash
cd "/mnt/jogos/Nome Do Jogo [FitGirl Repack]"
```

**4. Chame o descompactador:**

```bash
~/FitGirlWine/fitgirl
```

É isso. Se preferir não entrar na pasta, passe ela como argumento:

```bash
~/FitGirlWine/fitgirl "/mnt/jogos/Nome Do Jogo [FitGirl Repack]"
```

Se parar no meio — queda de energia, você cancelou, qualquer coisa — rode o
mesmo comando de novo e ele continua de onde estava.

Se algo não funcionar, `~/FitGirlWine/fitgirl doctor` diz o que falta no seu
sistema.

### Para digitar só `fitgirl`

Opcional, só para não repetir o caminho:

```bash
mkdir -p ~/.local/bin && ln -s ~/FitGirlWine/fitgirl ~/.local/bin/fitgirl
```

Se `~/.local/bin` já estiver no seu `PATH` — é o caso na maioria das
distribuições — a partir daí basta `fitgirl` em qualquer pasta.

## O que acontece quando você roda

A ferramenta conduz tudo pelo terminal, nesta ordem:

| Pergunta | O que Enter faz |
|---|---|
| Idioma da interface | escolhe português |
| Onde instalar | aceita o primeiro disco da lista |
| Idiomas e opcionais do jogo | mantém o padrão do repack para cada item |
| Limitar CPU e memória manualmente | responde "não": a ferramenta se ajusta sozinha |
| Revisar e iniciar | **começa a descompactar** |

Ou seja, dá para atravessar o fluxo inteiro só dando Enter — lembrando que o
último Enter é o que inicia o trabalho. Até ali, nada é escrito no disco.

Duas exceções ao "Enter aceita": se nenhum disco gravável for detectado, ou
se o destino escolhido não passar na validação, aí ele pede um caminho
completo, e aí não há padrão a aceitar.

Para automatizar, `FITGIRL_LANGUAGE=pt` ou `FITGIRL_LANGUAGE=en` dispensa a
pergunta de idioma.

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

O resto existe para **manter a ferramenta**, e não é necessário para
descompactar nada:

| Caminho | O que é |
|---|---|
| `tools/` | build e empacotamento |
| `tests/` | suíte automatizada |
| `docs/` | arquitetura, validação, pendências e solução de problemas |
| `third_party/` | licenças e fontes correspondentes dos componentes de terceiros |
| [`investigacao/`](investigacao/) | **tudo o que é pesquisa**: evidências, análise de instaladores e material antigo |

A pasta [`investigacao/`](investigacao/) é a parte do repositório que existe
para **descobrir como os instaladores funcionam** e provar que a ferramenta os
reproduz corretamente. É trabalho de quem mantém o projeto. Quem só quer
descompactar um repack não precisa de nada que esteja lá.

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
