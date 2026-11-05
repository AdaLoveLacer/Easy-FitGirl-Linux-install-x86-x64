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
   atualizar consumidores; `i18n.py` preserva imports antigos como alias para o
   mesmo módulo durante a transição.
8. **Em andamento:** mover a análise do setup para `planning/analyzer.py`.
   A primeira subetapa reúne a leitura das seções, campos, componentes e espaço
   declarado no ISS; commit do usuário pendente. A geração e coleta das
   evidências permanecem para as próximas subetapas.
9. Mover o fluxo do script compilado para `planning/script_flow.py`.
10. Mover a geração de plano para `planning/planner.py`.
11. Mover a auditoria para `planning/audit.py`.
12. Mover a coordenação das etapas para `execution/installer.py`.
13. Separar a persistência e retomada em `execution/journal.py`.
14. Mover a chamada de ferramentas de extração para `execution/extractor.py`.
15. Mover o monitor de progresso para `execution/monitor.py`.
16. Separar leitura e combinação de manifestos em `verification/manifests.py`.
17. Separar cálculo e conferência de hashes em `verification/checksums.py`.
18. Mover o relatório de integração para `verification/integration.py`.
19. Mover a descoberta e configuração do Wine para `platform/wine.py`.
20. Mover controle de processos e sinais para `platform/processes.py`.
21. Mover limites e detecção de recursos para `platform/resources.py`.
22. Mover checagens de compatibilidade para `platform/compatibility.py`.
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
A etapa 8 ainda está em andamento e só será contada após sua conclusão.

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
  atômica, incluindo movimentação, imports e cobertura necessária. Informar um
  nome de commit em português e avisar o usuário para criá-lo; o assistente não
  faz commits nem push. Relatar testes, resultado, limitações e próxima etapa;
  parar para revisão do usuário.
- Ao concluir ou bloquear uma etapa, atualizar `status/project-status.json`,
  executar `python3 tools/sync-docs.py --write` e verificar com `--check`.

Na etapa 2, a interface real foi percorrida em inglês até o cancelamento. Alguns
textos dessa opção já permaneciam em português no código anterior à mudança;
corrigi-los requer uma etapa separada de localização.
