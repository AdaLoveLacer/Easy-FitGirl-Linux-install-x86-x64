# Reestruturação incremental do código-fonte

Este documento registra a **estrutura alvo**, as decisões de nomenclatura e o
método de migração acordados em 2026-11-05. A árvore abaixo não descreve o estado
atual inteiro: cada diretório passa a existir somente quando sua responsabilidade
é movida e validada. A arquitetura em operação está em [ARCHITECTURE.md](ARCHITECTURE.md),
e os requisitos do produto permanecem em [REQUIREMENTS.md](../REQUIREMENTS.md).

## Estrutura alvo

```text
fitgirl                          # Único comando público
packaging/
└── desktop/
    └── fitgirl.desktop          # Atalho opcional que abre fitgirl em um terminal
src/
└── fitgirl_installer/
    ├── cli/
    │   ├── main.py              # Entrada e roteamento dos comandos
    │   ├── menus.py             # Perguntas e escolhas no terminal
    │   └── presentation.py      # Páginas, rótulos, tamanhos e mensagens
    ├── planning/
    │   ├── analyzer.py          # Evidências extraídas do setup
    │   ├── script_flow.py       # Fluxo do script compilado do instalador
    │   ├── planner.py           # Construção da sequência de etapas
    │   └── audit.py             # Provas exigidas e recusa de planos inseguros
    ├── execution/
    │   ├── installer.py         # Coordenação das etapas do plano
    │   ├── extractor.py         # Chamada do backend de extração
    │   ├── journal.py           # Estado, ordem, transações e retomada
    │   └── monitor.py           # Progresso observado durante a extração
    ├── verification/
    │   ├── manifests.py         # Leitura e combinação de manifestos
    │   ├── checksums.py         # Cálculo e conferência de hashes
    │   └── integration.py       # Relatório dos arquivos no destino
    ├── platform/
    │   ├── wine.py              # Descoberta e configuração do Wine
    │   ├── processes.py         # Processos, sinais e encerramento
    │   ├── resources.py         # CPU, memória e prioridade
    │   ├── compatibility.py     # Requisitos do sistema
    │   └── runtime.py           # Preparação do runtime privado
    ├── translations.py          # Traduções e idioma ativo
    └── models.py                # Tipos realmente compartilhados
libexec/
└── fitgirl-extract              # Backend interno de extração
tests/                            # Testes do comportamento público e interno
tools/                            # Análise, build e manutenção
docs/                             # Documentação
manifests/                        # Planos auditados
third_party/                      # Fontes e licenças de terceiros
evidence/                         # Evidências técnicas
status/                           # Estado canônico do projeto
.work/                            # Desenvolvimento local ignorado pelo Git
```

`script_flow.py` e `translations.py` são os nomes escolhidos. `models.py` deve
conter apenas tipos usados por mais de uma área; ele não é depósito de funções.
Os diretórios `planning/`, `execution/`, `verification/` e `platform/` serão
criados na migração, não antecipadamente com arquivos vazios.
Os arquivos `__init__.py` necessários aos pacotes foram omitidos da árvore para
destacar as responsabilidades; o pacote `cli` pode reexportar `main` enquanto
os imports existentes dependerem de `fitgirl_installer.cli`.

## Limites entre responsabilidades

- `fitgirl` continua chamando o CLI e é o único entrypoint público. O CLI recebe
  escolhas e apresenta resultados; a execução não deve depender de prompts.
- `planning/` lê evidências do ISS e do script compilado, gera etapas e as audita.
  A auditoria recusa ações ou condições sem prova; mover código não muda esse gate.
- `execution/` executa o plano auditado. O instalador coordena; `journal.py`
  persiste estado e retomada; `extractor.py` chama `libexec/fitgirl-extract`;
  `monitor.py` observa progresso real.
- `verification/` interpreta manifestos e confere integridade. `platform/`
  concentra acesso ao Wine, processos e recursos do host. `translations.py`
  mantém o idioma e as mensagens existentes.
- Cada função deve ter uma finalidade clara, estar no módulo dono dessa
  finalidade e declarar suas dependências. Funções de coordenação podem chamar
  funções especializadas; não devem incorporar a lógica delas nem criar ciclos
  de importação. A migração preserva a lógica antes de qualquer simplificação.

O atalho `packaging/desktop/fitgirl.desktop` representa a possibilidade de abrir
um **emulador de terminal** a partir do ambiente gráfico e executar `fitgirl`
nele (`Terminal=true`, com `Exec=fitgirl` após a instalação). Não é uma
interface gráfica do instalador. É uma proposta futura, fora da
refatoração atual, e sua distribuição deverá respeitar o requisito de um único
artefato público em `dist/`. O código do CLI não deve depender do atalho.

## Sequência incremental

1. **Concluída — `60e4247`:** converter `cli.py` em pacote, preservando
   `from fitgirl_installer.cli import main` e a execução por `python -m`.
2. **Concluída — `83009da`:** mover somente `_wizard_page`, `_component_label` e
   `format_size` para `cli/presentation.py`, preservando nomes importáveis.
3. **Concluída — `a3365e6`:** mover `prompt_yes_no`, `prompt_path`,
   `prompt_positive_int` e `prompt_cpu_list` para `cli/menus.py`.
4. **Concluída — `6f4dcc1`:** mover `prompt_components` para `cli/menus.py`,
   mantendo suas dependências de apresentação explícitas.
5. **Concluída — `8c62e6f`:** mover o menu e a seleção de destino para
   `cli/menus.py`, injetando serviços de armazenamento e validação.
6. **Concluída — `53b8770`:** mover seleção de idioma, parser, roteamento e
   tratamento de erros para `cli/main.py`; `cli/__init__.py` mantém uma fachada
   lazy para os imports existentes.
7. **Concluída — `ded94e8`:** renomear `i18n.py` para `translations.py` e
   atualizar consumidores; `i18n.py` preservou imports antigos como alias para o
   mesmo módulo durante a transição e foi removido depois que nenhum código
   o usava mais.
8. **Concluída:** mover a análise do setup para `planning/analyzer.py`.
   A leitura de seções, campos, componentes e espaço declarado no ISS foi
   movida em `e7f96a7`, e a descoberta das ferramentas de análise em
   `48c9e33`. A atualização da auditoria foi separada da função que gera o
   plano em `192cf13`. A aplicação dos bloqueios semânticos foi movida para o
   analisador em `5abf8ae`; a coordenação da auditoria foi movida em `6281466`,
   com serviços explícitos e fachada no CLI. A desmontagem do código compilado
   foi movida em `84879b1`, e a execução do innounp em `d0520a7`. A montagem
   do comando nativo ou Wine foi movida em `68c9972`; a leitura e verificação
   do cache foram movidas em `ece6bb8`, e a montagem dos metadados de análise
   em `dd588ca`. A identificação do setup foi movida em `176630c`, a
   verificação das ferramentas obrigatórias em `6e3b113`, e o cálculo dos
   caminhos do cache em `79048cf`. Por fim, a coordenação de
   `generate_manifest_draft` (reaproveitar, regenerar ou analisar do zero) foi
   movida para o analisador, com os colaboradores declarados em
   `AnalysisServices`; o CLI mantém uma fachada que monta esses serviços.
9. **Concluída:** mover o fluxo do script compilado para
   `planning/script_flow.py`. O antigo `ifps_ir.py` (leitura do disassembly
   IFPS, grafo de controle conservador, condições constantes e máscara de
   componentes) foi movido inteiro, sem mudança de lógica; `planner.py`,
   `plan_audit.py`, o CLI e os testes passaram a importar o novo módulo, e o
   arquivo antigo foi removido por não ter mais consumidores.
10. **Concluída:** mover a geração de plano para `planning/planner.py`. O
    módulo foi movido inteiro, sem mudança de lógica, e seus imports internos
    passaram a apontar para `analyzer` e `script_flow` no mesmo pacote. O CLI,
    `plan_audit.py`, `tools/plan-from-disassembly.py` e os testes importam o
    novo caminho; o `planner.py` antigo foi removido.
11. **Concluída:** mover a auditoria para `planning/audit.py`. O antigo
    `plan_audit.py` foi movido inteiro, sem mudar regras, mensagens nem o
    formato de `plan-audit.json`; o CLI, `tools/audit-plan.py`, os testes e
    `PLAN_AUDIT.md` usam o novo caminho, e o arquivo antigo foi removido. Com
    as etapas 8 a 11, o pacote `planning/` está completo; o manifesto, o
    grafo de controle e o relatório de auditoria de um repack sintético saem
    idênticos aos do código anterior à sequência.
12. **Concluída:** mover a coordenação das etapas para
    `execution/installer.py`. Como `install()` dependia de cerca de 40
    funções do CLI, a coordenação saiu em partes: a seleção das etapas
    (`enabled`, `step_key`, `selected_steps`) e o peso de cada uma no
    progresso global (`weighted_steps`) em `5bfd614`; o laço que executa as
    etapas, com despacho por tipo numa tabela de tratadores
    (`run_planned_steps`), em `8f03159`; o fechamento (`finish_installation`)
    em `e4ae25a`; e, por fim, a preparação do destino e do scratch e a
    execução completa (`run_installation`), com o pedido em `InstallRequest`
    e os colaboradores em `InstallServices`. O `install()` do CLI ficou com a
    escolha do plano e dos componentes e com a retomada do journal, que vai
    para `journal.py` na etapa 13; os `run_*` seguem no CLI, ligados por
    adaptadores, até as etapas 13 a 15.
13. **Concluída:** separar a persistência e retomada em
    `execution/journal.py`. Passo preparatório em `90fcd45`: `InstallerError`
    foi para `models.py`, para o journal e o CLI o compartilharem sem import
    circular. Depois saíram a gravação atômica com `.bak`, a leitura e a
    recuperação do journal corrompido (`0679e3b`); o estado inicial, a
    validação e a retomada que recusa rodar ao lado de uma etapa viva
    (`520f6c8`); o monitoramento da ordem em produção (`bb51f3e`), com testes
    de caracterização escritos antes da mudança; e as transações (backup com
    reflink, rollback confinado, recuperação na retomada e finalização). O
    `begin_transaction` do journal recebe os caminhos por uma função chamada
    só depois da checagem de `rollback_paths`; o CLI mantém um invólucro com a
    assinatura antiga e o `transaction_paths`, que depende da resolução de
    caminhos das etapas e segue com os executores.
14. **Concluída:** mover a chamada de ferramentas de extração para
    `execution/extractor.py`. Primeiro saiu a chamada do backend
    `libexec/fitgirl-extract` (`run_extract`, `e6f63e3`), com os
    colaboradores em `ExtractionServices`: resolução e confinamento de
    caminhos, conferência do volume de origem, prefixo de recursos e
    execução do processo. Depois saiu a materialização dos payloads `tmp` e
    `app` do setup pelo innoextract, com staging atômico, retomada pelo
    journal e adoção do payload legado, recebendo o hash, a espera do
    processo e o innoextract padrão por `PayloadServices`. A conferência MD5
    do volume segue no CLI até a etapa 17, e o controle de processos até a
    etapa 20; o CLI mantém invólucros com as assinaturas antigas. Os
    executores de pós-processamento (`batch`, `exec`, `isexec`, remoção,
    cópia, combinação de manifestos e INI) não são ferramentas de extração
    e continuam no CLI.
15. **Concluída:** mover o monitor de progresso para `execution/monitor.py`.
    O módulo foi movido inteiro, sem mudança de lógica; como roda como
    script, chamado por caminho pelo `libexec/fitgirl-extract`, só o
    `sys.path` que localiza o pacote subiu um nível. O backend, o teste e o
    `TROUBLESHOOTING.md` usam o novo caminho, e o arquivo antigo foi
    removido. Com as etapas 12 a 15, o pacote `execution/` está completo.
16. **Concluída:** separar leitura e combinação de manifestos em
    `verification/manifests.py`. Primeiro saiu a leitura (`parse_manifest`
    e a expressão `LINE`) do `verify.py` (`c453bf3`), que continua sendo o
    script de conferência chamado pela etapa `verify` e passa a importá-la
    do novo módulo. Depois saiu a combinação: `manifest_parts` escolhe o
    manifesto base e os addons ativos e recusa addon incompleto ou hash
    conflitante; `write_combined_manifest` grava o resultado de forma
    atômica e o valida antes de publicar. O `run_manifest_merge` do CLI
    mantém a checagem do comando comprovado, a transação, a preservação do
    verificador e a cópia do manifesto base, na mesma ordem.
17. **Concluída:** separar cálculo e conferência de hashes em
    `verification/checksums.py`. Primeiro saiu o cálculo: `file_hash` e
    `sha256` do CLI e `md5` do `verify.py`, com os corpos idênticos; o CLI
    os reexporta. As cópias de `sha256` em `planning/` não foram unificadas,
    porque isso seria simplificação, não movimentação. Depois saiu a
    conferência MD5 dos volumes de origem (`verify_archive`), que recebe o
    confinamento de caminhos e a gravação do journal como colaboradores; o
    CLI mantém um invólucro com a assinatura antiga. Por fim saiu a
    conferência de uma árvore contra o manifesto (`main`, com a gravação
    do estado de verificação): o `verify.py` ficou como ponto de entrada
    mínimo no mesmo caminho, para que o comando da etapa `verify`, a saída
    do `--dry-run` e o `--help` continuem iguais.
18. **Concluída:** mover o relatório de integração para
    `verification/integration.py`. O módulo foi movido inteiro, sem mudança
    de lógica; o CLI e o teste da política de integração importam o novo
    caminho, e o arquivo antigo foi removido. Com as etapas 16 a 18, o
    pacote `verification/` está completo.
19. **Concluída:** mover a descoberta e configuração do Wine para
    `platform/wine.py`. Primeiro saiu a descoberta (`discover_wine`, com o
    override de desenvolvimento, o Wine privado, `/mnt`, o Wine do sistema e
    o Proton, e `select_codec_runtime`, que escolhe o primeiro que responde
    a `--version`). A raiz do projeto, a preparação do Wine privado e a
    própria descoberta chegam como parâmetros, para que o CLI continue
    resolvendo-os na hora da chamada (`dddbd15`). Depois saiu a
    configuração: a conversão de caminhos para o Wine (`wine_z_path` e
    `wine_path`, com `C:`, `W:` e `winepath`) e a preparação do prefixo
    (`ensure_wine_prefix`, com `wineboot` e o drive `W:` apontando para
    `/mnt`), que recebe a execução do processo e o diretório de trabalho.
20. **Concluída:** mover controle de processos e sinais para
    `platform/processes.py`: a execução de um processo registrado no journal
    (`run_process` e `wait_process`), o repasse de SIGINT/SIGTERM
    (`SignalForwarder` e `forwarding_signals`) e o envio de sinal ao grupo
    ativo usado por `fitgirl pause` e `resume` (`signal_active_group`). A
    gravação do journal chega como colaborador (`save_state`), para que
    `platform/` não dependa de `execution/`; o CLI mantém invólucros com as
    assinaturas antigas.
21. **Concluída:** mover limites e detecção de recursos para
    `platform/resources.py`. Primeiro o antigo `resource_limits.py`
    (detecção de CPUs, memória e limite do cgroup, e leitura da lista de
    CPUs) foi movido inteiro, sem mudança de lógica (`89d33ad`); o CLI, os
    menus e os testes importam o novo caminho, e o arquivo antigo foi
    removido. Depois saiu do CLI a aplicação dos limites a um comando
    (`command_prefix`: escopo `systemd-run` com MemoryHigh/MemoryMax,
    `taskset` e `nice`), com o corpo idêntico.
22. **Concluída:** mover checagens de compatibilidade para
    `platform/compatibility.py`. O módulo (arquitetura, glibc, Python,
    bibliotecas, comandos e o relatório de `fitgirl doctor`) foi movido
    inteiro, sem mudança de lógica; o CLI importa o novo caminho e o
    arquivo antigo foi removido. O `import platform` dele continua
    resolvendo para o módulo padrão.
23. Mover a preparação do runtime para `platform/runtime.py`.

### Métrica de conclusão

O progresso global usa estas 23 etapas conceituais: bootstrap do pacote CLI,
apresentação, prompts simples, menu de componentes, menu de destino, roteamento
CLI, traduções, quatro módulos de planejamento, quatro de execução, três de
verificação e cinco de plataforma. O percentual é etapas concluídas dividido
por 23, arredondado ao inteiro mais próximo. O atalho desktop opcional e
`models.py` (condicional à necessidade de tipos compartilhados) não entram na
métrica. Antes da etapa 6, cinco etapas estavam concluídas: **22%**. Com a
etapa 6, são seis de 23: **26%**. Com a etapa 7, são sete de 23: **30%**.
Com a etapa 8, são oito de 23: **35%**. Com a etapa 9, são nove de 23: **39%**. Com a etapa 10, são dez de 23: **43%**. Com a etapa 11, são onze de 23: **48%**. Com a etapa 12, são doze de 23: **52%**. Com a etapa 13, são treze de 23: **57%**. Com a etapa 14, são catorze de 23: **61%**. Com a etapa 15, são quinze de 23: **65%**. Com a etapa 16, são dezesseis de 23: **70%**. Com a etapa 17, são dezessete de 23: **74%**. Com a etapa 18, são dezoito de 23: **78%**. Com a etapa 19, são dezenove de 23: **83%**. Com a etapa 20, são vinte de 23: **87%**. Com a etapa 21, são 21 de 23: **91%**. Com a etapa 22, são 22 de 23: **96%**.

Esta ordem não autoriza juntar responsabilidades em um commit. Se um grupo
apresentar dependências cruzadas, reduzi-lo antes da movimentação. O estado
intermediário deve funcionar e pode manter fachadas de compatibilidade; elas são
removidas apenas quando seus consumidores forem migrados.

## Validação e commits

- Antes de cada etapa, conferir o estado do Git e preservar alterações existentes
  do usuário. Registrar o comportamento e as falhas de base.
- Fazer uma mudança conceitual pequena. Preservar interface pública, formatos,
  mensagens, ordem, efeitos e retomada. Não misturar correções, funcionalidades,
  dependências nem formatação incidental com a movimentação.
- Usar `.work/` para scratch e logs; antes de testes Python, criar `.work/tmp` e
  exportar seu caminho absoluto em `TMPDIR`. A suíte de base passa **100/100**
  com `FITGIRL_LANGUAGE=pt`. Sem a variável, 21 testes de subprocesso falham por
  `EOF` no seletor de idioma; isso precede a refatoração.
- Após cada alteração, executar os testes relevantes. Antes do commit, executar
  a suíte completa, checar sintaxe, documentação sincronizada e diff. Onde o
  comportamento afetado for interativo, abrir `fitgirl` em terminal real com
  entrada segura; validar o artefato standalone quando a mudança alcançar o
  pacote. Um ensaio cancelado antes de instalar não prova extração real.
- Corrigir qualquer falha nova antes de commitar. Preparar uma etapa funcional
  atômica, incluindo movimentação, imports e cobertura necessária. O assistente
  cria o commit local após a validação, com mensagem natural em português, faz
  o push em seguida e informa por voz o usuário a cada commit. Se o push falhar,
  relatar o motivo e resolver o bloqueio antes da próxima etapa. Relatar testes,
  resultado e limitações; continuar para a próxima etapa sem pausa obrigatória.
- Ao concluir ou bloquear uma etapa, atualizar `status/project-status.json`,
  executar `python3 tools/sync-docs.py --write` e verificar com `--check`.

Na etapa 2, a interface real foi percorrida em inglês até o cancelamento. Alguns
textos dessa opção já permaneciam em português no código anterior à mudança;
corrigi-los requer uma etapa separada de localização.
