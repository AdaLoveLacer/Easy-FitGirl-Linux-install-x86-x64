# Troubleshooting técnico

Este documento registra sintomas, medições, causas e correções confirmadas. A
existência de um processo Wine **não** é considerada prova de progresso.

## FreeArc fica em execução, mas não lê nem grava

### Sintoma confirmado

- `unarc-helper.exe` permanece vivo;
- um thread pode consumir aproximadamente 100% de **um núcleo** (cerca de 8,3%
  do total em uma CPU com 12 threads);
- `pidstat -d` mostra 0 KiB/s;
- o descritor de `fg-01.bin` permanece na posição 31;
- o primeiro arquivo de saída permanece com zero bytes.

### Causa

Wine Bug 59472: **FreeArc hangs on startup in new WoW64 mode**. O construtor
`LargestMemoryBlock` do FreeArc faz uma busca binária defeituosa pela maior
alocação possível. O novo WoW64 aceita uma alocação inicial que o Windows não
aceita; há overflow no cálculo do ponto médio e um loop infinito alternando
`NtAllocateVirtualMemory`/`NtFreeVirtualMemory`.

A pilha capturada no caso FM7 mostrou o thread preso em `NtFreeVirtualMemory`.

Fontes:

- https://bugs.winehq.org/show_bug.cgi?id=59472
- https://bugs.winehq.org/show_bug.cgi?id=50824 (workaround que originou o patch usado)
- https://list.winehq.org/hyperkitty/list/wine-bugs@list.winehq.org/message/24ZXNXCQSI547WH3ZPKGETLBDDGQUBFI/

### Correção usada

Teste histórico com Wine 11.14 patched de BrandowLucas:

- projeto: https://github.com/BrandowLucas/fitgirl-wine
- arquivo: `wine-11.14-fitgirl-amd64.tar.xz`
- SHA-256: `de504c1f6f407bf619040fccfe1f7a32de8c3384fe97c061efea8c3d368d6db5`

Ele incluía a reserva do topo do espaço de endereçamento de 32 bits e patches
relacionados a Unarc/pZLib. Essa versão foi removida do pacote de publicação
porque sua correspondência completa de fontes e patches não foi demonstrada.
Instale Wine ou Proton compatível no sistema; o launcher também aceita
`FITGIRL_WINE_BIN`.

Mais precisamente, `virtual.patch` rejeita reservas WoW64 maiores que
`2 GiB - 1`, impedindo o overflow da sondagem do Unarc. O próprio projeto informa
que a correção equivalente entrou no Wine 11.16; o build 11.14 validado ainda
precisa do patch. Mensagens `allocate_virtual_memory out of memory` durante essa
sondagem não provam falta de RAM física: podem ser rejeições intencionais do
espaço virtual de 32 bits.

## Caixa “Can't open read file mapping!”

### Sintoma confirmado

`FreeArcExtract` abre o arquivo, cria o primeiro destino e inicia
`CLS-srep_x64.exe`, mas o worker exibe uma caixa de erro e fica esperando em
`ntsync_schedule`, sem CPU e sem I/O.

### Causa

Os `cls-*.dll` universais usam shared memory para conversar com os workers
`cls-*_x64.exe`/`x86.exe`. O host original ISDone/Inno cria um mapping de 256
bytes chamado `Init_MapFile_`. O prefixo dos demais objetos IPC fica dentro
desse mapping. Um host standalone que chama apenas `FreeArcExtract` não cria
essa inicialização automaticamente.

Sem ela, o worker procura mappings como `Read_MapFile_CLS-srepXX`, recebe
`ERROR_FILE_NOT_FOUND` e mostra a caixa de erro.

### Correção usada

Antes de carregar `unarc.dll`, `unarc-helper.exe` faz:

```c
HANDLE mapping = CreateFileMappingA(
    INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, 0, 256, "Init_MapFile_");
char *view = MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, 256);
memcpy(view, "Global\\", 8); /* inclui NUL */
```

O mapping e sua view permanecem vivos até `FreeArcExtract` retornar.

Resultado empírico: `fg-06.bin` passou de erro de mapping para extração completa,
`FreeArcExtract rc=0`, produzindo 8,6 MiB.

Referências:

- https://github.com/Bioruebe/UniExtract2/issues/82
- https://soyuka.me/forza-horizon-6-linux-offline-saves/

## FreeArc/pZLib falha em pipes

Wine Bug 59984 descreve uma diferença em
`NtSetInformationFile(FilePositionInformation)` para pipes anônimos. Alguns
caminhos de stream pZLib/Unarc dependem do comportamento do Windows.

Fonte: https://bugs.winehq.org/show_bug.cgi?id=59984

## `fg-01.bin` avança e termina com `rc=1`

Este caso é diferente do Wine #59472 e do mapping CLS:

- os callbacks `read` avançaram até `y=1695416351`;
- o worker ativo no último intervalo era `cls-magic2_x64.exe`;
- houve CPU e I/O reais;
- havia aproximadamente 219 GiB livres;
- o helper e os workers encerraram, sem deadlock ou processo órfão.

A causa confirmada no FM7 era a ordem incompleta: `fg-06.bin` precisa ser
extraído para `{tmp}` antes de `fg-01.bin`, pois materializa os codecs `xt3/xt4`.
Com esse bootstrap, `fg-01` produziu 2.237 arquivos e todos passaram no MD5. O
primeiro helper também ocultava eventos finais quando eles reutilizavam os mesmos
valores `x/y`; por isso o exit code do Wine não deve ser descrito automaticamente
como retorno do DLL.

`WINEDEBUG=+seh` não registrou page fault ou exceção não tratada. O código
`0x80000026` observado no fim é unwind de saída, compatível com encerramento
deliberado. O próximo nível de tracing recomendado é `--wine-debug +process`,
para descobrir qual worker termina primeiro e qual exit code propaga ao host.

### Hipótese de memória SREP acima do limite aceito

O payload do caso FM7 contém duas informações conflitantes:

- `CLS.ini`: `Memory=60%-2048m` em `[Srep]`;
- `English.ini`: aviso para inicializar SREP com valor não superior a 4096 MiB.

O instalador original pode materializar o template com base na opção de limite
de RAM. O standalone agora aceita `--srep-memory 4096`, que altera somente essa
chave no `CLS.ini` extraído. Isso é uma hipótese experimental, ainda não uma
correção confirmada.

No FM7, `Memory=4096m` sozinho não alterou o resultado e a hipótese foi refutada
para esse volume.

## `Not an SREP compressed file: -` no início do volume

No `fg-03.bin` do FM7, esse texto era um erro downstream. O bloco compactado
começa com `BZ3v1`; ao decodificar o primeiro frame BZip3, a saída começa com
`SREP`. A cadeia correta é, portanto, BZip3 → SREP.

O `arc.ini` continha o comando abaixo ainda sem materialização:

```ini
unpackcmd = bzip3.exe -dc -j fgrplc - - <stdin> <stdout>
```

Com `fgrplc` literal, BZip3 não alimentava o próximo estágio e SREP recebia EOF.
O backend agora substitui o placeholder por `nproc` ou pelo valor explícito de
`--bzip3-threads`. A validação real mostrou `bzip3.exe -dc -j 4 - -`, SREP ativo,
leitura contínua do volume e crescimento do destino.

### `TempPath={app}` fora do Inno

`{app}` é uma constante do Inno Setup. Um helper que chama `FreeArcExtract`
diretamente não a expande. Deixar `TempPath={app}` literal pode impedir SREP ou
outros CLS de criar temporários. O orquestrador agora substitui todas as
ocorrências em `CLS.ini` pelo scratch convertido para caminho Wine.

No FM7, a expansão foi comprovadamente aplicada e não mudou o resultado; não é
a causa isolada dessa falha específica.

### Worker CLS termina com `-9` / status Linux 247

No caso FM7, tracing Linux da árvore Wine mostrou `CLS-srep_x64.exe` chamando
`exit_group(-9)`. `cls-magic2_x64.exe` propagou o mesmo valor logo depois. O
status 247 é apenas `-9` reduzido a oito bits; não significa que o processo foi
morto por sinal 247. Esse resultado descarta OOM killer, segfault e encerramento
externo nessa reprodução, mas ainda não distingue erro de dados, EOF/I/O ou
falha do transporte CLS porque o worker não expôs sua mensagem ao callback.

Mover apenas os caminhos para `C:` também não corrigiu o FM7. Ao testar isso,
confirme na linha de processo e em `CLS.effective.ini` que aparecem caminhos
`C:\...`; prefixos armazenados sob `/mnt` exigem que `drive_c` tenha precedência
sobre o mapeamento genérico de `/mnt` para `W:`. Essa precedência foi corrigida
no orquestrador.

### Override experimental de `CLS-srep.dll`

Há relatos independentes de que algumas versões do adaptador `CLS-srep.dll`
falham no transporte por memória compartilhada sob Wine. Para isolar essa
camada sem trocar os executáveis SREP do repack, use
`--cls-srep-dll ARQUIVO`. A ferramenta preserva a DLL original como
`CLS-srep.original.dll` e registra ambos os hashes em `CLS-srep.sha256`. Essa
opção não implica compatibilidade entre versões e o projeto não distribui uma
DLL alternativa.

Para reproduzir sem alterar a instalação principal:

```bash
./libexec/fitgirl-extract -d /caminho/do/repack -t /destino/diagnostico \
  -w /scratch/diagnostico --archive fg-01.bin --monitor-interval 5 \
  --wine /caminho/wine-fitgirl/bin/wine --prefix /caminho/prefixo
```

## Como determinar se há progresso real

Use uma janela de amostragem, não o `%CPU` acumulado do `ps`:

```bash
pidstat -p PID -u -d -r 1 10
cat /proc/PID/io
cat /proc/PID/fdinfo/FD
```

Critérios usados pelo módulo interno `src/fitgirl_installer/execution/monitor.py`:

1. delta de `read_bytes` e `write_bytes` dos processos;
2. posição do descritor do volume `fg-*.bin`;
3. crescimento lógico e quantidade de arquivos no destino;
4. CPU instantânea, separando “percentual de um núcleo” de “percentual total”;
5. processos `unarc-helper`, `CLS-srep`, Magic/Lollypop, BZip3, Precomp e X5.

CPU alta isoladamente **não** prova progresso. O bug 59472 é justamente um
busy-loop com CPU alta e zero avanço de arquivo.

