# Investigação

Esta pasta é a parte de **pesquisa** do projeto. Ela existe para descobrir
como os instaladores da FitGirl funcionam e para provar que a ferramenta os
reproduz corretamente.

Nada aqui é necessário para descompactar um repack. Quem só quer usar a
ferramenta pode ignorar esta pasta inteira — veja o [README](../README.pt-BR.md).

## O que tem aqui

| Caminho | O que é |
|---|---|
| `evidence/` | registros das validações feitas em repacks reais: hashes, estados de journal, relatórios de auditoria |
| `docs/ANALYSIS_TOOLS.md` | como preparar o innounp e o disassembler IFPS usados na análise |
| `docs/PLAN_AUDIT.md` | como a auditoria confere o plano gerado contra o bytecode do instalador |
| `docs/EXPERIMENTS.md` | o histórico dos experimentos, com o que funcionou e o que não |
| `docs/REESTRUTURACAO.md` | o plano da reestruturação do código e seu andamento |
| `tools/bootstrap-analysis.sh` | instala as ferramentas de análise localmente, sem sudo, com hashes fixados |
| `tools/audit-plan.py` | roda a auditoria de um plano |
| `tools/plan-from-disassembly.py` | gera um plano a partir do disassembly do script compilado |
| `tools/pascalscript-cli.rs`, `tools/pascalscript-dll-function-names.patch` | o adaptador do parser IFPS e seu patch |
| `tools/*-progress-terminal.py` | visualizações de progresso usadas em ensaios manuais |
| `legacy/` | material antigo preservado |

## Por que isso é separado

A ferramenta é um descompactador: o usuário aponta para o repack e ela
descompacta, usando a estrutura de etapas que vem de dentro do próprio
instalador. A análise estática não faz parte desse caminho — ela é como
*nós* verificamos que a reprodução está certa, e como novas versões da
`ISDone.dll` entram no catálogo.

Misturar as duas coisas na raiz do repositório dava a impressão errada de que
o usuário precisaria auditar algo antes de descompactar. Não precisa.
