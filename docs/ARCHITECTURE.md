# Arquitetura atual

O projeto possui um único comando público, `fitgirl`. O controle permanece no
Linux; Wine é usado somente como ABI para DLLs, codecs e pós-processamentos PE.
O `setup.exe` é lido como contêiner e fonte de metadados, mas nunca é executado.

Arquivos para visualização externa com pan/zoom:

- [`architecture.pdf`](architecture.pdf) — diagrama vetorial pronto;
- [`architecture.dot`](architecture.dot) — fonte Graphviz versionável.

## Plataforma e pré-requisitos

O runtime atual é Linux x86-64 com glibc 2.38 ou superior e Python 3.12 ou
superior. O limite da glibc vem do maior símbolo exigido pelos binários ELF
fixados (`unarc` e ferramentas do runtime); versões inferiores são recusadas
antes de iniciar prompts ou instalação. Wine precisa estar instalado pelo
usuário para carregar DLLs e codecs Windows do repack.

O código Python usa somente a biblioteca padrão. O host fornece glibc, loader
ELF, `libstdc++`, `libgcc_s` e `liblzma`. O artefato inclui as bibliotecas Boost,
bzip2, zlib e zstd exigidas pelo `innoextract`, com avisos e inventário de hashes
no ZIP. Wine não é empacotado; `fitgirl doctor` procura Wine ou
Proton no PATH, nos locais usuais do Steam e em `FITGIRL_WINE_BIN`. Os demais comandos de sistema exigidos pela interface e
pelo backend também são verificados centralmente. `findmnt` só alimenta a lista
automática de discos; `taskset` e `nice` só são necessários ao solicitar essas
opções avançadas.

Em Debian/Ubuntu, os nomes dos pacotes correspondentes são `libc6` (na versão
mínima), `libstdc++6`, `libgcc-s1`, `python3` (3.12+), `bash`, `coreutils`, `tar`,
`gzip`, `gawk` ou `mawk`, `grep`, `sed`, `util-linux` e Wine (ou Proton
compatível). O artefato traz Boost e bibliotecas de compressão que o
`innoextract` usa; Wine e codecs continuam dependências do sistema ou do repack.

Debian 13, Ubuntu 24.04 LTS e CachyOS rolling x86-64 foram exercitados. Isso não
declara compatibilidade com toda distribuição que satisfaz a versão mínima: a
checagem `fitgirl doctor` informa host, bibliotecas, comandos e limites, e a
matriz empírica continua restrita a esses três ambientes. Ela não detecta todas
as bibliotecas Wine carregadas dinamicamente nem prova todos os codecs.

```mermaid
flowchart TD
    U[Usuário: fitgirl /repack] --> D[Pacote standalone da release<br/>com fontes e licenças]
    D --> CLI[CLI e menu terminal]

    subgraph ORIGEM[Repack somente leitura]
        SETUP[setup.exe]
        VOLS[fg-*.bin e opcionais]
    end

    CLI --> WINE[Wine ou Proton do sistema<br/>instalado pelo usuário]
    CLI --> DISC[Descoberta e SHA-256 do setup]
    SETUP --> DISC
    DISC --> CACHE{Plano auditado<br/>já existe?}
    CACHE -- sim --> PLAN[Manifesto/IR comprovado]
    CACHE -- não --> COMP[ISS + IFPS<br/>IR, CFG e análise simbólica]
    COMP --> GATE{Ordem, condições e<br/>ações foram provadas?}
    GATE -- não --> REFUSE[Recusar instalação<br/>draft/review_required]
    GATE -- sim --> PLAN

    PLAN --> MENU[Componentes, destino externo<br/>e recursos; runtime automático]
    MENU --> STATE[Journal atômico<br/>install-state.json]
    STATE --> RESUME{Etapa já concluída?}
    RESUME -- sim --> NEXT[Próxima etapa]
    RESUME -- não --> PAYLOAD

    subgraph SCRATCH[Scratch no filesystem do destino]
        PAYLOAD[Payload seletivo auditado<br/>39 tmp + _Redist]
        RUNTIME[Cópia runtime isolada<br/>por extração]
        TX[Snapshots/reflinks e<br/>quarentena reversível]
        LOGS[Logs, monitor e estado]
    end

    SETUP -->|innoextract seletivo| PAYLOAD
    PAYLOAD -->|SHA-256 e conjunto exato| STATE
    PAYLOAD -->|--payload-ready| RUNTIME
    RUNTIME --> LOCAL[Aplicar BZip3, SREP,<br/>CLS e caminhos somente na cópia]

    NEXT --> KIND{Tipo da etapa}
    STATE --> KIND
    VOLS --> MD5[Validar MD5 do volume]
    KIND -- extract --> MD5
    MD5 --> BACKEND[fitgirl-extract<br/>um volume por vez]
    LOCAL --> BACKEND

    subgraph CODEC_WINE[Wine como ABI — não incluído na release]
        HELPER[unarc-helper.exe PE32]
        DLL[unarc.dll do próprio repack]
        CODECS[SREP, Magic2, Lollypop,<br/>BZip3, X5 e outros filtros]
        POST[Pós-processamentos PE/batch]
        HELPER --> DLL --> CODECS
    end

    BACKEND --> HELPER
    CODECS --> APP[Destino da instalação]
    KIND -- ini-write --> INI[Escrita INI atômica]
    INI --> STATE
    KIND -- isexec / batch / exec --> SNAP[Definir rollback_paths]
    SNAP --> TX --> POST
    POST --> COMMIT{Código zero?}
    KIND -- delete-file / delete-tree --> QUAR[Renomear para quarentena]
    QUAR --> TX

    COMMIT -- não --> ROLLBACK[Restaurar snapshot/quarentena]
    ROLLBACK --> INCOMPLETE[Manter etapa incompleta]
    INCOMPLETE --> STATE
    COMMIT -- sim --> DONE[Marcar etapa concluída]
    BACKEND --> DONE
    QUAR --> DONE
    DONE --> STATE
    DONE --> MORE{Restam etapas?}
    MORE -- sim --> NEXT

    BACKEND --> MON[Monitor real:<br/>posição, I/O, CPU e saída]
    POST --> MON
    MON --> LOGS

    MORE -- não --> VERIFY[Verificar fitgirl.md5<br/>e manifests addon]
    APP --> VERIFY
    VERIFY -- falha --> FAIL[Não finalizar transações]
    VERIFY -- sucesso --> FINAL[Preservar QuickSFV e manifests<br/>descartar backups/quarentenas]
    FINAL --> OK[Instalação confirmada em 100%]

    subgraph DOCS[Documentação e build]
        STATUS[status/project-status.json]
        SYNC[tools/sync-docs.py]
        CHECK[Teste e build recusam<br/>documentação obsoleta]
        STATUS --> SYNC --> CHECK
    end
    CHECK --> D
```

## Invariantes

- volumes seguem a ordem compilada do instalador, nunca ordem lexical;
- payload auditado é imutável durante a extração; ajustes ocorrem na cópia runtime;
- uma etapa só entra em `completed` após retorno bem-sucedido;
- falha ou sinal deixa a menor etapa segura retomável;
- remoções permanecem em quarentena até a verificação final;
- processos vivos sem avanço de posição, I/O ou saída não contam como progresso;
- caminhos de rollback ficam confinados ao destino e ao scratch;
- documentação operacional é gerada da fonte canônica e verificada por teste/build.

## Backends

1. **FreeArc nativo:** serve para formatos abertos, mas não lê descritores FA
   Protect (`descriptor failed CRC check`).
2. **FreeArcExtract customizado:** o helper PE32 carrega o `unarc.dll` extraído
   do repack e deixa que ele invoque somente os codecs exigidos pelo volume.
