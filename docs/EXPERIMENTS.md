# Diário de experimentos

Este arquivo preserva resultados empíricos, inclusive tentativas que falharam.
Uma hipótese só é marcada como causa quando há medição ou reprodução que a
distinga das demais.

## 2026-10-27 — `fg-06.bin` como volume mínimo

- runtime: Wine 11.14 patched de `BrandowLucas/fitgirl-wine`;
- helper: PE32, carregando o `unarc.dll` retirado do próprio setup;
- sem `Init_MapFile_`: worker CLS mostra `Can't open read file mapping!`;
- com `Init_MapFile_` contendo `Global\\\0`: `FreeArcExtract rc=0`;
- resultado: 13 arquivos e aproximadamente 8,6 MiB.

Conclusão: Wine patched, helper, mapping CLS e caminhos `W:` funcionam juntos.

## 2026-10-27 — primeira extração completa

- primeiro volume: `fg-01.bin`;
- houve progresso real, diferente do busy-loop do Wine #59472;
- worker observado no último intervalo: `cls-magic2_x64.exe`;
- último callback registrado: `read`, `x=1616`, `y=1695416351`;
- posição do descritor observada anteriormente: aproximadamente 1,4 GiB;
- CPU agregada chegou a mais de dois núcleos e houve leitura física;
- destino não cresceu de forma persistente; o arquivo parcial foi removido;
- `FreeArcExtract` terminou com `rc=1`;
- espaço livre no destino após a falha: aproximadamente 219 GiB;
- não restaram helper ou workers órfãos.

O callback antigo imprimia somente quando `x/y` mudavam. Isso suprimiu o evento
final caso `error` reutilizasse os últimos contadores. Portanto, `rc=1` ainda não
identifica a causa. Não há evidência suficiente para atribuí-lo a CRC, memória,
pZLib ou Wine #59984.

## 2026-10-27 — instrumentação seletiva

O helper passou a:

- imprimir todos os eventos de controle, filename e erro;
- limitar somente eventos `read`/`write`, em passos de 64 MiB;
- registrar `message`, `x`, `y`, `extra`, retorno final e `GetLastError()`;
- usar uma linha por evento e `fflush`, preservando o fim do log em crashes.

Validação inicial: `fg-01.bin --list-only` retornou zero e registrou
`total_files=2401`, além de `origsize` e `compsize`. Uma extração isolada de
`fg-01.bin` foi iniciada em destino diagnóstico para capturar a falha completa.

A primeira reprodução isolada encerrou em `y=1528823839` sem emitir a linha
`[FreeArc] final`. Isso prova que o `rc=1` do processo Wine não era o retorno
capturado do DLL. Não houve OOM killer no journal nem coredump Linux; no momento
da inspeção ainda havia aproximadamente 12 GiB disponíveis e 36 GiB de swap
livre. Foi iniciada nova reprodução com `WINEDEBUG=+seh`.

O tracing mostrou muitas mensagens de falha em `VirtualAlloc` antes da extração.
Elas pertencem à sondagem `LargestMemoryBlock` e ao limite intencional do patch
WoW64, não ao OOM killer. Durante `magic2`, o worker chegou a cerca de 8,6 GiB de
espaço virtual e 3,2 GiB de RSS; depois continuou processando com múltiplos
threads e leitura real até aproximadamente 1,695 GiB.

A reprodução `WINEDEBUG=+seh` também terminou sem `page fault`, exceção não
tratada ou backtrace de crash. O único código SEH final foi `0x80000026`, usado
pelo unwind de saída. Novamente não houve `[FreeArc] final`. A hipótese atual é
encerramento deliberado do processo host depois que um worker retorna erro, não
segfault nem OOM físico. `WINEDEBUG=+process` confirmou que o DLL consulta
continuamente o worker com `NtQueryInformationProcess`; quando o worker some, o
host termina. Esse canal não expôs o exit code responsável no log.

Uma pista adicional veio do próprio payload: `English.ini` contém
`WARNING_INIT_SREP_BAD_PARAM`, informando que a inicialização SREP deve receber
no máximo 4096 MiB, enquanto o `CLS.ini` extraído usa `Memory=60%-2048m`. Em uma
máquina com 24 GiB isso pode resultar em valor muito superior a 4096 MiB. O
instalador original pode reescrever esse template conforme a opção de limite de
RAM; o host standalone não fazia isso. Foi adicionado `--srep-memory MIB` para
testar essa hipótese sem alterar as outras seções.

O primeiro teste dessa opção encontrou um bug na ferramenta: `CLS.ini` usa CRLF,
e o `\r` impedia reconhecer `[Srep]`. A edição foi corrigida normalizando as
linhas antes de comparar a seção. A validação mostrou `Memory=4096m` no arquivo
efetivamente consumido; essa é a execução que conta para testar a hipótese.

O teste com `Memory=4096m` corretamente materializado falhou no mesmo estágio;
logo, esse limite isolado não corrige o caso FM7. A opção foi mantida por ser útil
para outros repacks e para reproduções controladas.

Outra diferença concreta foi identificada: o `CLS.ini` ainda continha
`TempPath={app}`. Essa constante é expandida pelo Inno original, mas não pelo
helper standalone. A ferramenta passou a substituí-la pelo caminho Wine do
scratch antes de iniciar o FreeArc. O teste seguinte combina essa correção com o
limite SREP já validado.

O teste combinado confirmou no arquivo efetivo
`TempPath=W:\\disco de destino\\.fm7-diag-clstemp`, mas terminou no mesmo ponto sem
`[FreeArc] final`. Portanto, nem o limite de 4096 MiB nem a expansão de `{app}`
explicam isoladamente a falha do FM7. A expansão permanece necessária por
correção semântica para outros filtros e repacks.

### Exit code dos workers capturado no Linux

Uma reprodução completa sob `strace -f -e execve,exit_group` finalmente
capturou a causa imediata. O Wine iniciou os workers abaixo, nesta ordem:

1. `cls-magic2_x64.exe d - - -idx=00`;
2. `CLS-srep_x64.exe d - - -idx=00`.

O SREP chamou explicitamente `exit_group(-9)` e o Linux registrou status 247.
Em seguida, `magic2` também chamou `exit_group(-9)` e saiu com 247. Isso mostra
que não houve sinal fatal nem encerramento pelo kernel: `magic2` propagou o
erro negativo retornado pela etapa SREP. Depois disso o helper PE32 foi
encerrado antes de `FreeArcExtract` retornar, como nas reproduções anteriores.

O significado interno exato de `-9` nessa variante CLS ainda precisa ser
confirmado. O binário se identifica como SREP 3.93a beta e contém mensagens para
dados quebrados, EOF/erro de I/O e falha de escrita, mas o protocolo CLS não
encaminhou a mensagem correspondente ao callback do host.

### Scratch e destino realmente em `C:`

A primeira tentativa de testar `C:` descobriu um bug na conversão de caminhos:
como o próprio prefixo estava sob `/mnt`, a regra rápida de `W:` tinha prioridade
e convertia `PREFIX/drive_c/...` para `W:\...`. A conversão agora reconhece o
`drive_c` do prefixo primeiro. A linha de processo confirmou os argumentos
`-dpC:\fm7-target-cdrive`, `-wC:\fm7-diag-cdrive` e o `CLS.effective.ini`
confirmou `TempPath=C:\fm7-diag-cdrive`.

Mesmo com scratch, temporários CLS e destino realmente em `C:`, o SREP sumiu no
mesmo estágio e `magic2` propagou a falha. A recomendação de evitar drives
externos foi portanto testada corretamente e não resolve isoladamente o FM7.

### Adaptador CLS/SREP alternativo

O issue `Bioruebe/UniExtract2#82` contém duas evidências relevantes. Uma
reprodução de dezembro de 2024 relata que trocar apenas a família CLS/SREP
permitiu extrair alguns repacks sob Wine, embora alguns títulos Ubisoft ainda
falhassem. Em abril de 2026, outro participante publicou uma reimplementação em
C do adaptador `CLS-srep.dll`, atribuindo a falha Wine à visibilidade de objetos
de memória compartilhada nomeados sem o namespace `Global\\`.

Para separar adaptador e codec, foi adicionado `--cls-srep-dll ARQUIVO`. Ele
troca somente a DLL PE32; `cls-srep_x64.exe` e o restante do payload continuam
originais. O teste local usa uma compilação temporária do código de referência:

- fonte extraída do comentário: SHA-256
  `0387394931403bb48996905f9d891b2709f8d76a0ccdbeb8f703be9b86e8c3ba`;
- PE32 compilado localmente: SHA-256
  `46f3d7597c58ffd60125d4b3c1425187191583b20314fd1ef5caf7df60f09912`;
- DLL original do FM7: SHA-256
  `39c965edc8f577695dadd68d6d40ace4e1e17625ca4669e3f1321b6b26e470c7`.

Esses artefatos experimentais não foram adicionados ao projeto.

## Directive 8020 — rollback de pós-processamentos

O compilador de plano versão 9 atribuiu conjuntos mutáveis aos 13 `isexec`:
`arc.ini` para `fnr`, nenhum para `FlushFileCache`, arquivos exatos e temporários
para os dois patches `x.exe`, globs `work/*.txt`/`work/*.bat` para as seis
execuções de `fart`, `inner.fgpack` para o comando de remoção e a árvore `{app}`
completa para `build01.bat` e `x5n.exe`. Os dois últimos conjuntos são
intencionalmente conservadores porque o batch é código arbitrário e a sintaxe
`x5n -f . ... .` autoriza mutação em qualquer ponto da instalação.

O executor prefere reflink via `FICLONE` e cai para cópia independente quando o
filesystem não oferece CoW. Falha, sinal ou retomada antes da confirmação
restaura o snapshot. `DeleteFile` e `DelTree` foram implementados como rename
para `scratch/transactions`; as quarentenas permanecem disponíveis até a
verificação final e só então são removidas.

Durante o teste desse mecanismo, uma versão intermediária de
`restore_transaction` converteu um campo `root` ausente em `Path('.')` e iniciou
uma remoção do workspace não-Git. A reconstrução foi feita do banco de patches
do OpenCode e do cache do artefato. A suíte restaurada passou 49/49; depois da
validação explícita de raízes e backups, passou 54/54. Essa falha não atingiu os
repasses, instalações validadas nem evidências em `/tmp`, mas reforça a
necessidade de versionar o projeto antes de novos ensaios destrutivos.

Um smoke test posterior executou os dois primeiros pós-processamentos reais.
`fnr.exe` foi chamado por `cmd.exe`, atualizou `arc.ini` e retornou zero;
`FlushFileCache.exe` esvaziou os working sets e também retornou zero. As duas
transações chegaram a `committed`, foram registradas e tiveram seus backups
descartados por `finalize_transactions`. Esse teste também detectou e corrigiu
a passagem incorreta da expressão inteira de `{cmd}` como um único argumento:
agora o parser Windows entrega argumentos separados ao Wine e preserva
`expanded_quoted` para caminhos com espaços.

Na primeira extração integral do Directive 8020, o `unarc-helper.exe` entrou em
livelock no primeiro arquivo de `fg-01.bin`: aproximadamente um núcleo ocupado,
posição 31 constante, zero I/O e saída com zero bytes. O ensaio manual havia
usado o Wine 10 do sistema, não o Wine 11.14 preparado. A inspeção também revelou
que o backend executava `innoextract` novamente a cada volume e sobrescrevia os
INIs já mutados e registrados pelo planner. O backend agora aceita
`--payload-ready`, copia `setup-payload/tmp` para um diretório runtime único e
aplica somente nessa cópia os ajustes locais. Um teste executável confirmou os
hashes intactos no payload auditado, os ajustes presentes na cópia efetiva e a
remoção segura do staging; a retomada usa um prefixo novo com Wine 11.14.

## Directive 8020 — prefixo de fg-07 e recuperação do payload

A tentativa integral chegou a 84,3%, mas falhou na primeira execução de
`{tmp}/work/fart.exe` (código 53). O volume `fg-07.bin` contém o prefixo
`work/work`; o plano já registrava `archive_path_filter: work`, que o executor
ignorava. O backend agora recebe `--archive-path-filter work` e encaminha
`-apwork` ao FreeArc. Um ensaio real isolado produziu `work/fart.exe`,
`work/build01.bat` e os demais auxiliares no caminho esperado, sem mover ou
achatar a árvore após a extração.

Na recuperação foram preservados o journal e a árvore temporária; as quatro
escritas INI e `fnr.exe` foram reaplicados porque uma reconstrução legada havia
restaurado os originais, mantendo as etapas marcadas como concluídas. Somente
`fg-07.bin` foi reextraído; os volumes grandes permaneceram concluídos. A
retomada passou a verificar os arquivos auditados sem confundir auxiliares
adicionados pelos volumes com corrupção do payload. Divergência dos arquivos
auditados após etapas concluídas agora bloqueia reconstrução automática.

Uma segunda retomada chegou à substituição de 8.153 ocorrências pelo FART,
mas foi revertida porque seu retorno 217 era interpretado como erro. O fonte
upstream (`https://github.com/lionello/fart-it/blob/master/fart.cpp`) confirma
`return TotalFindCount`; o retorno observado equivale a `8153 & 255`. O executor
agora suporta a forma restrita `-w *.txt|*.bat find replace` com argumentos ASCII:
calcula previamente as substituições por palavra completa, exige a contagem
esperada no retorno e valida o resultado de cada arquivo byte a byte. Outras
formas não comprovadas são recusadas. Não se aceita qualquer código não zero.

Suíte após as correções: 57 testes aprovados. Evidências:
`evidence/auto-plan-directive-8020-2026-10-31/fg07-recovery.log` e
`filter-regression.log` no mesmo diretório.

Após queda de energia, a retomada concluiu `build01.bat`, `x5n.exe` e a extração
de `inner.fgpack`. A etapa posterior repetia `cmd /C del inner.fgpack`, embora
`delete_archive_after` já tivesse removido o intermediário. Isso produziu retorno
1 e interrompeu o fluxo. O executor agora reconhece somente `cmd /C del` com um
único nome literal e `rollback_paths` exatamente correspondente ao diretório de
trabalho: essa forma usa remoção nativa reversível e tolera ausência. Comandos
compostos ou fora desse escopo não são convertidos. Testes cobrem ausência,
quarentena/restauração e recusa de escopo divergente; suíte: 58 testes aprovados.

## Directive 8020 — instalação integral concluída

A etapa 44 terminou com 289/289 arquivos válidos, zero ausentes, zero divergências
e 38.194.436.754 bytes calculados em 371,263 segundos. O executor preservou
`fitgirl.md5`, QuickSFV e seu INI no destino e confirmou 100% somente depois da
verificação. O journal ficou com `active: null` e sem transações pendentes.
Destino: `/mnt/SOURCE_DISK/Games/Directive 8020 native validation`.

Esse resultado comprova o plano revisado usado no ensaio, incluindo retomada
após queda de energia durante `build01.bat`; não comprova execução do jogo nem
compatibilidade universal. Evidência compacta: `installation-success.log` e
`completed-install-state.json` em
`evidence/auto-plan-directive-8020-2026-10-31/`.

## Corpus novo e extração entre discos

Ferramentas IFPS/innounp recuperadas em armazenamento persistente. Star Trucker,
Children of Morta e Subnautica geraram planos com cobertura reconhecida completa
e auditoria consistente; somente o candidato isolado Star Trucker foi revisado
para execução. Seu comando `copy /b fitgirl.md5+*.addon&&del *.addon` revelou
uma lacuna: o verificador consultava apenas o manifesto base no payload.

O compilador versão 10 reconhece essa forma exata como `merge-manifests` nativo,
com snapshot de `_Redist`, preservação de `fitgirl.base.md5` e dos addons,
recusa de conjuntos parcialmente presentes e hashes conflitantes, publicação
atômica e verificação do manifesto combinado no destino. A preservação final
não sobrescreve esse manifesto com a base. Suíte: 68 testes aprovados.

O ensaio lê do disco disco de origem (`/dev/BLOCK_DEVICE`) e grava destino/scratch no disco de destino
(`/dev/BLOCK_DEVICE`). Três volumes passaram nos hashes de origem; saída estimada em
até 6,2 GiB, reserva conservadora de 22,4 GiB e aproximadamente 97 GiB livres.
Nenhum arquivo de trabalho novo é criado em `/tmp`.

### Star Trucker — loop do wrapper Razor em caminho longo

O core e o bônus concluíram, mas `fg-02.bin` ficou no primeiro arquivo
(`baselib.dll`), com o helper dormindo e sem I/O. A primeira leitura do monitor
foi enganosa: ele não incluía o processo `rzw`, sem sufixo `.exe`, que usava
98–100% de um núcleo (predominantemente chamadas de sistema).

Um ensaio isolado sob strace mostrou repetição de acessos ao mesmo diretório
`rzrXXXX`. O decoder `rz.exe`, invocado diretamente sobre o arquivo já preparado
pelo wrapper, informou que não conseguia abrir o caminho longo. Com exatamente
os mesmos bytes em `C:\rzprobe`, extraiu 99.004.860 bytes em 1,310 segundo.

O backend agora disponibiliza o diretório de trabalho por um drive curto
`R:` (ou outra letra livre), sem sobrescrever mappings existentes. Apenas o
caminho Windows muda; o armazenamento continua no scratch do disco de destino. O processo
travado e o wineserver desse prefixo foram encerrados, preservando o journal.
Na retomada, somente `fg-02.bin` foi repetido: FreeArc retornou zero, a combinação
de manifestos concluiu e a verificação MD5 final foi iniciada.

O monitor passou a reconhecer nomes reais dos codecs, incluindo `rzw` e `rz`,
com filtro opcional por prefixo Wine. CPU ocupada sem I/O/saída/posição em avanço
continua sendo informada como progresso não comprovado, não como sucesso.

A retomada final do Star Trucker concluiu com 224/224 hashes válidos no manifesto
combinado (core e bônus), zero ausentes, zero divergências e 6.632.164.425 bytes
verificados em 109,556 segundos. O manifesto combinado não foi sobrescrito na
preservação final; base e addon originais também permaneceram disponíveis.
Journal inativo, transações finalizadas. Isso valida o ensaio revisado entre
discos, não a inicialização do jogo nem compatibilidade universal.

## Informação de tamanho no menu

O compilador versão 11 preserva o literal positivo
`[Setup].ExtraDiskSpaceRequired` como metadado opcional. O menu soma setup e
volumes locais sem ler seu conteúdo; no resumo, soma somente os arquivos de
origem das etapas selecionadas, sem contar volumes repetidos ou intermediários.
Não invoca codecs nem dispara análise nova para calcular os tamanhos.

Planos legados podem consultar o ISS já existente no cache, sem modificar o
manifesto revisado ou o hash do journal. Para Mirage 7, a extração prévia dos
metadados confirmou 2.503.000.000 bytes extras declarados (2,33 GiB), contra
899,97 MiB de setup e volumes compactados. O texto distingue essa declaração
do tamanho final exato e alerta sobre opcionais, scratch e rollback. Ausência,
valores dinâmicos, negativos, zero ou declarações duplicadas não produzem uma
estimativa inventada. Suíte: 73 testes aprovados.

## Wine privado no artefato

**Estado histórico, substituído pela política de publicação de 2026-11-04:**
esta seção registra um build local antigo. A release atual não incorpora esse
runtime; exige Wine instalado pelo usuário. Consulte `docs/THIRD_PARTY.md`.

O build passou a incorporar o pacote completo Wine 11.14 FitGirl, fixado pelo
SHA-256 `de504c1f6f407bf619040fccfe1f7a32de8c3384fe97c061efea8c3d368d6db5`.
O arquivo original tem 94.001.784 bytes; seus arquivos regulares somam
815.582.708 bytes. Não houve tentativa de remover bibliotecas do runtime.

O provisionador verifica plataforma, espaço e hashes, usa lock e staging no
XDG_DATA_HOME e publica atomicamente. Cache já preparado é reutilizado; dados
alterados não são sobrescritos. Testes cobrem esse fluxo, corrupção,
escape de caminhos, plataforma, destinos fora do prefixo e detecção Proton na
versão-fonte. A suíte total chegou a 86 testes aprovados após cobrir discos
distintos, validação da lista de CPUs e isolamento do journal entre destinos
irmãos do mesmo jogo.

O menu não solicita versão/caminho Wine; lista `Games` em todos os dispositivos
locais distintos e oferece um caminho completo personalizado. O prefixo dos
codecs permanece separado do jogo. O artefato completo foi aberto em terminal
externo com dados privados no disco de destino. A instalação Mirage 7 extraiu os dois
volumes; uma falha de compatibilidade do plano legado deixou de materializar o
manifesto. A correção recuperou apenas `_Redist` e executou o MD5, sem reextrair:
238/238 arquivos, 2.500.148.966 bytes, zero ausentes e divergências. Evidência em
`.work/logs/private-runtime-onscreen.log` e `.work/logs/mirage-public-recovery.log`.

O menu avançado passou a explicar SREP, BZip3, afinidade, `nice`, `MemoryHigh` e
`MemoryMax`, com limites derivados da afinidade, RAM disponível e cgroup. A busca
do QuickSFV x64 validado é automática e fixada por hash; sua ausência não impede
o verificador MD5 Linux.
Portabilidade em outras distribuições e revisão de redistribuição seguem como
gates pendentes.

## Vinculação binária, integração e telemetria de recursos

Star Trucker, Children of Morta e Subnautica foram redesmontados diretamente de
seus `CompiledCode.bin`. As três saídas coincidiram byte a byte com os textos
usados pelo planner e mantiveram zero divergências na auditoria. Isso fecha a
proveniência binário→disassembly, sem promover os drafts: condições e ordem por
caminho ainda exigem prova independente. Evidência em
`evidence/compiled-binding-2026-11-02/`.

O monitor passou a registrar RSS, PSS, picos e afinidade agregados dos workers e
a sinalizar retrocesso real da posição de leitura para o mesmo PID sobrevivente.
No `fg-01.bin` do Mirage 7, três extrações completas produziram exatamente
2.432.644.838 bytes cada. Picos medidos: automático, 4.017 MiB RSS e 3.946 MiB
PSS; SREP 2.048 MiB, 4.180/4.106 MiB; SREP 4.096 MiB, 4.181/4.107 MiB. Portanto,
`Memory` do SREP não funciona como teto global do pipeline e não reduziu o pico
neste corpus. Evidência em `evidence/performance-resources-2026-11-02/`.

Uma execução adicional com afinidade `0-1` e BZip3 em duas threads concluiu em
232,781 segundos. Todos os 96 samples de helper, Magic2, SREP e XTool permaneceram
em `0-1`, comprovando herança de afinidade nos workers observados.

Depois de o usuário ajustar o overclock, uma carga `stress-ng matrixprod` usou
12 workers a 100% por cinco minutos: 12 aprovados, zero falhas e zero métricas
marcadas como não confiáveis. A suíte e o build também concluíram durante a
carga. Esse resultado é evidência curta de estabilidade, não substitui ensaio
térmico prolongado.

## 2026-11-02 — calibração de progresso, ETA e pausa real

O `fg-06.bin` do FM7 concluiu com 13 arquivos e 8.911.707 bytes em 6,246
segundos com prefixo aquecido. O volume é curto demais para sustentar duas
amostras úteis de ETA; o resultado correto é manter `?` em vez de inventar uma
previsão.

No `fg-01.bin` do Mirage 7, a posição da entrada chegou a 99,9% enquanto os
workers continuaram escrevendo por pelo menos 70 segundos. O monitor foi
calibrado para chamar essa fase de `PÓS-LEITURA` e manter `ETA=?`. Uma repetição
com a correção produziu 79 arquivos e 2.432.644.838 bytes, sem `ETA=0s`.

Na instalação integral separada do Mirage, `pause` enviou `SIGSTOP` ao grupo sob
carga real. Todos os processos ficaram em estado `T` e os deltas de CPU/I/O e
saída permaneceram zero por 20 segundos. `resume` enviou `SIGCONT`, a leitura
voltou a avançar em cinco segundos e o fluxo terminou com 238/238 MD5 válidos,
zero ausentes e divergências.

Também foi adicionada uma política operacional de integração. Após sucesso, o
scratch recebe inventário de executáveis, redistribuíveis e arquivos de registro.
DirectX/VC++ são preservados sem execução, registros não são importados e atalhos
ou runners não são configurados, pois executar o jogo está fora do escopo. Relatórios de Directive 8020,
Star Trucker e Mirage 7 estão em `evidence/integration-policy-2026-11-02/`.
