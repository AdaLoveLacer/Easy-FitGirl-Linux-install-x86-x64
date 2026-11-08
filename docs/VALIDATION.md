# Checklist histórico de validação

A tabela de veredito abaixo é sincronizada com o estado atual. As caixas das
seções A–G preservam um checklist anterior e não são a lista atual de pendências;
resultados posteriores e tarefas abertas estão em [`PENDENCIAS.md`](PENDENCIAS.md)
e na fonte canônica [`project-status.json`](../status/project-status.json).
Não reescreva essas caixas como se fossem o estado atual.

Estados: `PASS`, `PARCIAL`, `PENDENTE`, `BLOQUEADO` ou `N/A`.

## Veredito atual

<!-- BEGIN GENERATED:PROJECT_STATUS -->

Fonte canônica: [`status/project-status.json`](../status/project-status.json).  
Suíte automatizada descoberta: **113/113 testes**.

| Requisito | Estado | Veredito |
|---|---:|---|
| Qualquer instalador FitGirl | PARCIAL | Não há alegação universal: só planos auditados são aceitos; planos novos sem prova ficam bloqueados para revisão. |
| Repacks integralmente validados | PASS | FM7, Mirage 7 e The Darkness 2 |
| Retomada por etapa | PASS | Falhas e sinais reais preservam a menor etapa reiniciável |
| Seleção de opcionais | PASS | Idiomas do The Darkness 2 e ramo 4K do FM7 validados |
| Barra de progresso | PASS | Calibrada no fg-06 do FM7 e fg-01 do Mirage; pós-leitura mantém ETA desconhecida sem anunciar término |
| Teto de RAM | PASS | MemoryMax via systemd-run --scope aplica limite cgroup v2; escopo real medido em 768 MiB. Não promete estabilidade: atingir o teto pode encerrar a etapa. Ainda não houve repack inteiro sob teto reduzido. |
| Teto de CPU | PASS | Afinidade 0-1 medida em 96 amostras do Mirage fg-01 nos quatro workers observados: unarc-helper, Magic2, SREP e XTool. Resultado limitado a esse pipeline/corpus. |
| Instalação completa do FM7 | PASS | 1080p e ramo 4K validados |
| Directive 8020 | PASS | Plano revisado: instalação integral concluída, MD5 289/289, zero ausentes e divergências; journal inativo e transações finalizadas |
| Star Trucker com bônus | PASS | Plano revisado entre discos: 224/224 arquivos MD5 válidos no manifesto combinado, zero ausentes e divergências |
| Gate de sucesso | PASS | Extração e pós-processamento concluídos, estrutura final e MD5/CRC sem ausências ou divergências; abrir o jogo está fora do escopo |

<!-- END GENERATED:PROJECT_STATUS -->

## A. Compatibilidade entre repacks (registro histórico)

- [x] `PASS` — inventariar instaladores locais: 16 setups FitGirl encontrados.
- [x] `PASS` — confirmar núcleo comum: `unarc.dll`, `arc.ini`, `CLS.ini` e
  `ISDone.dll` aparecem nas amostras.
- [x] `PASS` — provar que ordem lexicográfica é inválida: FM7 exige
  `fg-06 → fg-01 → fg-02 → opcional → mover → fg-03 → fg-04 → fg-05`.
- [x] `PASS` — gerar automaticamente um rascunho do FM7 a partir do ISS e do
  disassembly: oito etapas e sete MD5 recuperados corretamente.
- [ ] `PENDENTE` — extrair ISS/CompiledCode de pelo menos três repacks adicionais:
  um pequeno, um com `fg-selective-*` e um recente com filtros diferentes.
- [ ] `PENDENTE` — comparar automaticamente plano gerado com bytecode para cada um.
- [x] `PASS Mirage 7` — instalação completa do repack pequeno: dois volumes,
  238/238 arquivos, 2.500.148.966 bytes, 0 ausentes e 0 divergências.
- [x] `PASS The Darkness 2` — ramo inglês seletivo concluiu: core 146/146 e
  addon 14/14 no MD5, com reconstrução e extração transacional de `eng.fgpack`.
- [ ] `PENDENTE` — verificar idiomas, arquivos opcionais ausentes e pós-processamento.
- [ ] `PENDENTE` — remover a alegação “qualquer FitGirl” até esses testes passarem.

**Critério de aceite:** no mínimo três famílias reais passam do `inspect` à
verificação final, sem regras específicas embutidas no código Python.

## B. Falhas, corrupção e retomada (registro histórico)

- [x] `PASS sintético` — journal é gravado atomicamente após cada etapa.
- [x] `PASS sintético` — falha forçada na etapa 2 preserva a etapa 1.
- [x] `PASS sintético` — segunda execução pula a etapa 1 e repete somente a 2.
- [x] `PASS sintético` — MD5 alterado em volume já concluído impede o skip.
- [x] `PASS sintético` — journal não fica com processo ativo depois de erro normal.
- [x] `PASS sintético` — `SIGKILL` no orquestrador preserva a etapa ativa no journal.
- [x] `PASS real Mirage 7` — `SIGKILL` durante `unarc-helper.exe` deixou o grupo
  ativo; uma execução concorrente foi recusada, o grupo foi encerrado e a mesma
  etapa foi retomada. Resultado: 82 arquivos, 2.432.770.597 bytes; 79 arquivos
  cobertos pelo manifesto real passaram com zero mismatch.
- [x] `PASS` — `SIGINT` e `SIGTERM` são encaminhados ao grupo ativo e deixam o
  journal imediatamente retomável.
- [x] `PASS` — cópia corrompida de volume real foi recusada antes de iniciar Wine.
- [x] `PASS` — journal truncado foi preservado e restaurado do backup atômico.
- [x] `PASS real mount loss` — daemon FUSE derrubado durante leitura de
  `fg-02.bin`; FreeArc falhou, a etapa não foi concluída, o mesmo caminho foi
  remontado e retomado. Saída: 162 arquivos, 67.629.887 bytes e 159/159 hashes
  presentes válidos.
- [x] `PASS progresso real` — `fg-02.bin` do Mirage 7 manteve progresso global
  monotônico em 99,9% durante o flush e confirmou 100% somente após sucesso.
- [x] `PASS unitário` — ETA por janela móvel, ponderação global e retenção da
  última posição após saída do worker possuem cobertura automatizada.
- [x] `PASS sintético` — grupo sobrevivente bloqueia uma segunda execução concorrente.
- [x] `PASS sintético` — depois de encerrar o grupo, a etapa interrompida é repetida.
- [ ] `PENDENTE` — matar helper/worker Wine durante um volume real pequeno.
- [ ] `PENDENTE` — relançar e confirmar replay somente do volume interrompido.
- [ ] `PENDENTE` — corromper deliberadamente uma cópia de volume real e confirmar
  erro MD5 antes de iniciar Wine.
- [ ] `PENDENTE` — alterar arquivo final e validar contra `_Redist/fitgirl.md5`.
- [x] `PASS sintético` — verificador distingue OK, divergente e ausente e reutiliza cache.
- [x] `IMPLEMENTADO` — plano FM7 termina com verificação automática de `fitgirl.md5`.
- [ ] `PENDENTE` — executar a verificação automática após todos os volumes reais.
- [x] `CAUSA ENCONTRADA` — no `fg-03`, `fgrplc` literal impedia o BZip3 de
  alimentar o SREP; o backend agora substitui o placeholder por threads válidas.

**Critério de aceite:** nenhum crash pode marcar etapa incompleta como concluída;
ao retornar, somente a menor unidade reiniciável é repetida. Em volume sólido,
essa unidade é o volume inteiro, não o último byte ou arquivo mostrado.

## C. Opções equivalentes às do instalador (registro histórico)

- [x] `PASS sintético` — componente não selecionado é pulado.
- [x] `PASS sintético` — `--component` inclui a etapa condicional.
- [x] `PASS estático FM7` — `vid4k` corresponde ao componente e ao volume 4K.
- [x] `PASS estático FM7` — ausência do volume desativa o componente.
- [x] `PASS FM7` — ramo sem 4K executou o fallback `mover.bat`.
- [x] `PASS FM7 4K` — 35 vídeos opcionais foram extraídos; `mover.bat`
  preservou todos e adicionou somente `sizzle.bk2`; aplicação transacional final
  terminou com 36 arquivos 2160p e backup 1080p.
- [ ] `PENDENTE` — seleção interativa em terminal; atualmente as opções são flags.
- [ ] `PENDENTE` — idiomas `fg-selective-*` e dependências entre opções.
- [ ] `PENDENTE` — política Linux para DirectX/VC++ e prefixo alvo correto.
- [ ] `PENDENTE` — atalhos, registro e ações pós-instalação seguras.

**Critério de aceite:** `inspect` deve listar as mesmas escolhas relevantes do
Inno, e cada escolha deve alterar etapas/artefatos exatamente como o original.

## D. Progresso e observabilidade (registro histórico)

- [x] `PASS` — monitor mede I/O, posição do descritor, saída, arquivos e CPU.
- [x] `PASS` — estagnação é distinguida de processo apenas vivo.
- [x] `IMPLEMENTADO` — barra ASCII usa posição do volume/tamanho comprimido.
- [x] `PASS unitário` — formato desconhecido, 50% e limite ativo de 99,9%.
- [x] `PASS real` — calibrar barra no `fg-06` do FM7 e no `fg-01` do Mirage 7.
- [x] `PASS real` — progresso global ponderado pelo tamanho comprimido permaneceu
  monotônico e limitado a 99,9% até a confirmação da etapa.
- [x] `PASS` — distinguir `LEITURA` de `PÓS-LEITURA`, rotular a posição como
  entrada comprimida e sinalizar releituras internas por PID.
- [x] `PASS real` — ETA usa janela móvel durante leitura e permanece `?` sem
  amostras ou na fase pós-leitura; nenhum `0s` foi anunciado no volume calibrado.

**Critério de aceite:** a barra nunca anuncia 100% antes de `FreeArcExtract rc=0`
e sempre mantém os indicadores objetivos disponíveis no log.

## E. RAM e CPU (registro histórico)

- [x] `PASS sintético` — `--srep-memory` chega ao backend.
- [x] `PASS FM7` — `CLS.effective.ini` mostrou `Memory=4096m`.
- [ ] `PENDENTE` — medir RSS/PSS/peak dos workers com 2048, 4096 e padrão.
- [ ] `PENDENTE` — confirmar quais codecs ignoram o limite SREP.
- [ ] `PENDENTE` — decidir se um teto global via cgroup v2 é seguro; `ulimit`/OOM
  pode apenas matar o stream e não deve ser chamado de estabilidade.
- [x] `PASS sintético` — backend recebeu exatamente a afinidade pedida.
- [x] `PASS sintético` — ajuste relativo de `nice` foi herdado pelo backend.
- [x] `PASS parcial real` — afinidade foi confirmada em `unarc-helper` e
  `CLS-srep`; Magic2 e XCompress ainda precisam de amostragem equivalente.
- [x] `PASS real` — pausa/retomada atingiu os quatro processos observados e a
  saída retomada terminou com 159/159 hashes presentes válidos.
- [x] `PASS benchmark real` — `fg-02.bin` do Mirage 7 levou 10,071 s (2 CPUs),
  12,634 s (4), 11,725 s (6) e 7,437 s (12). O volume curto mostrou overhead e
  não permite assumir escalabilidade monotônica para outros codecs/volumes.

**Critério de aceite:** “CPU máxima” significa número máximo de CPUs lógicas por
afinidade. “RAM máxima” só será anunciado quando todos os processos estiverem
sob um mecanismo medido; até lá existe apenas limite interno do SREP.

## F. Tratamento global de erro (registro histórico)

- [x] `PASS` — exceções esperadas convergem no handler global do Python.
- [x] `PASS` — código diferente de zero não marca etapa como concluída.
- [x] `PASS FM7` — extrações podem encerrar o host com código zero sem devolver
  controle ao helper; esse caso é marcado como provisório e exige MD5 final.
- [x] `PASS` — ausência da linha final com código diferente de zero permanece falha.
- [x] `PASS` — manifesto/hash/opções divergentes recusam journal incompatível.
- [x] `PASS` — caminhos de manifesto não podem escapar das raízes permitidas.
- [ ] `PENDENTE` — testar `SIGINT`, `SIGTERM`, falta de espaço e filesystem read-only.
- [ ] `PENDENTE` — testar perda do mount de origem/destino durante uma etapa.
- [x] `PASS` — journal truncado recuperado por backup; original inválido mantido
  com sufixo `corrupt-<timestamp>` para diagnóstico.

## Execução dos testes leves

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile src/fitgirl_installer/*.py src/fitgirl_installer/cli/*.py tools/plan-from-disassembly.py
bash -n libexec/fitgirl-extract
```

Os testes sintéticos não carregam Wine, CLS ou arquivos grandes e podem rodar
enquanto o FM7 está sendo extraído.

## G. Pós-processamento transacional (registro histórico)

- [x] `PASS unitário` — falha de `isexec` restaura o conteúdo original.
- [x] `PASS unitário` — retomada reverte uma etapa que retornou, mas não chegou
  ao registro `completed`.
- [x] `PASS unitário` — remoções são renames para quarentena e podem ser
  restauradas.
- [x] `PASS unitário` — raiz ausente ou fora de `scratch/transactions` é
  recusada antes de qualquer remoção.
- [x] `PASS unitário` — finalização elimina somente quarentenas confinadas.
- [x] `PASS planner real` — 13/13 `isexec` do Directive 8020 receberam
  `rollback_paths`; versão do compilador: 9.
- [x] `PASS smoke real` — `fnr.exe` atualizou `arc.ini` e
  `FlushFileCache.exe` concluiu via Wine; ambos foram commitados e as cópias de
  rollback foram finalizadas.
- [ ] `PENDENTE real` — validar os snapshots de árvore completa exigidos por
  `build01.bat` e `x5n.exe`, incluindo custo sem reflink.

Suíte após a recuperação e o endurecimento: **54/54 testes**.

- [x] `PASS isolamento do payload` — `--payload-ready` usa uma cópia runtime por
  extração; ajustes de BZip3, SREP e `{app}` não alteram os hashes de `arc.ini` e
  `CLS.ini` materializados e auditados.
