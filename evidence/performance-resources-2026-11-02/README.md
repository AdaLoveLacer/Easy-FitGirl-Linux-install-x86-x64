# Recursos no Mirage 7 fg-01.bin

O monitor foi ampliado para registrar RSS/PSS, picos, afinidade dos workers e
releituras internas por PID. As extrações usam Wine privado e saída descartável
no disco de destino; cada execução completa produziu 2.432.644.838 bytes antes da remoção
do target de ensaio.

| Perfil | Pico RSS | Pico PSS | Resultado |
|---|---:|---:|---:|
| automático | 4.017 MiB | 3.946 MiB | concluído |
| SREP 2.048 MiB | 4.180 MiB | 4.106 MiB | concluído |
| SREP 4.096 MiB | 4.181 MiB | 4.107 MiB | concluído |

O valor SREP não é teto global. A memória total inclui helper, Magic2, SREP,
XTool e Wine; limitar apenas SREP não reduziu o pico neste volume. `MemoryMax`
do cgroup continua sendo o mecanismo rígido e pode encerrar a etapa.

`memory-matrix.json` contém os resultados estruturados.

Uma quarta extração completa aplicou `taskset 0-1` ao backend e BZip3 com duas
threads. Ela terminou em 232,781 segundos, produziu os mesmos 2.432.644.838 bytes
e todos os 96 samples registraram exclusivamente `cpus=0-1`. Foram observados
`unarc-helper.exe`, `cls-magic2_x64.exe`, `CLS-srep_x64.exe` e `xtool.exe`.
O resultado estruturado está em `affinity-0-1.json`.

Após ajuste do overclock pelo usuário, `stress-ng` executou `matrixprod` com 12
workers, carga de 100%, verificação habilitada e duração de 300 segundos. Todos
os 12 workers passaram, com zero falhas e zero métricas não confiáveis. Consulte
`cpu-stability.json` e `cpu-stability.log`.

## Calibração de progresso e ETA

O `fg-06.bin` do FM7 tem 1.851.170 bytes e produziu 13 arquivos/8.911.707 bytes
em 6,246 segundos com prefixo aquecido. É curto demais para formar uma janela de
ETA estável; nesse caso o monitor mantém `ETA=?`. Consulte
`fg06-calibration.json` e `.log`.

No `fg-01.bin` do Mirage 7, a entrada comprimida de 920.907.781 bytes chegou ao
fim muito antes do pós-processamento. A execução calibrada levou 91,157 segundos,
produziu os 79 arquivos/2.432.644.838 bytes esperados e registrou 15 amostras em
`PÓS-LEITURA`, cobrindo ao menos 70 segundos. Todas mantiveram `ETA=?`; nenhuma
anunciou zero segundo. O monitor agora rotula explicitamente `entrada`, `LEITURA`
e `PÓS-LEITURA`, pois não existe denominador genérico confiável para o trabalho
restante de SREP/XTool. Consulte `large-volume-calibration.json` e `.log`.

## Pausa e retomada sob carga real

Uma instalação nova do Mirage 7 foi pausada durante atividade comprovada de
Magic2/unarc: em três segundos, os ticks de CPU passaram de 57 para 174 e a
leitura agregada de 34.938.880 para 346.091.520 bytes. Após `SIGSTOP`, todos os
seis processos observados ficaram em estado `T` por 20 segundos, com deltas zero
de CPU, leitura, escrita e saída. Depois de `SIGCONT`, a leitura avançou de
360.566.784 para 818.606.080 bytes em cinco segundos. A instalação terminou com
as três etapas concluídas e MD5 238/238, zero ausentes e divergências. Evidência:
`pause-resume.json` e `.log`.
