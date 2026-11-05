# Requisitos canônicos do produto

Este arquivo é a fonte de verdade dos requisitos definidos pelo usuário. Deve
ser revisado antes de mudanças arquiteturais e atualizado antes de compactações
de contexto quando houver decisão nova.

Última atualização: 2026-11-05

## Objetivo principal

Fornecer **um único comando/arquivo distribuível para terminal Linux** que
receba um diretório de FitGirl Repack e instale o jogo sem executar a interface
gráfica nem o fluxo original de `setup.exe`.

Exemplo de interface pretendida:

```bash
fitgirl /caminho/do/repack
```

Depois desse comando, destino, componentes e opções devem ser coletados por um
menu interativo no terminal. O Wine é uma dependência do sistema usada somente
como ABI para codecs; o artefato não incorpora Wine. A interface pública não
deve exigir flags.

## Definição de sucesso

Uma instalação é bem-sucedida quando a extração e os pós-processamentos
auditados terminam, a estrutura final esperada existe e os manifestos FitGirl
validam todos os arquivos sem ausências, divergências MD5 ou erros CRC.

Abrir o jogo, testar jogabilidade, criar atalhos, importar registro ou configurar
um runner não fazem parte do escopo e não bloqueiam o resultado.

O repositório pode manter código-fonte modular para desenvolvimento e testes,
mas o usuário final deve receber **um único artefato e um único entrypoint não
ambíguo**. Scripts auxiliares não podem parecer instaladores alternativos.

## Requisitos funcionais obrigatórios

1. Detectar `setup.exe`, volumes e metadados do repack.
2. Obter a ordem real do instalador; nunca assumir ordem lexical dos volumes.
3. Reproduzir componentes, condicionais, opcionais e `fg-selective-*`.
4. Executar extração e pós-processamento sem abrir o instalador gráfico.
5. Usar Wine somente quando necessário como ABI para DLL/codecs Windows.
6. Medir progresso por evidência real: I/O, posição, CPU, arquivos e saída.
7. Processo vivo sem avanço não pode ser anunciado como progresso.
8. Suportar afinidade, prioridade, SREP, BZip3 e cgroup v2.
9. Manter retomada transacional por menor etapa reiniciável segura.
10. Não remover intermediários antes da conclusão confirmada da etapa seguinte.
11. Validar arquivos contra `_Redist/fitgirl.md5` e manifestos `.addon`.
12. Preservar `QuickSFV.EXE`, `QuickSFV.ini`, `fitgirl.md5` e `*.addon`.
13. Execuções longas devem usar background, journal e logs persistentes.
14. Não alegar compatibilidade universal sem validações empíricas suficientes.
15. Derivar automaticamente o plano de instalação do ISS e do
    `CompiledCode.bin`; manifestos específicos por jogo devem funcionar como
    cache auditável/override, não como trabalho manual obrigatório normal.
16. Quando a análise automática não conseguir provar uma condição, recusar a
    execução ou pedir revisão explícita em vez de adivinhar.

## Interface e organização obrigatórias

- Um único nome público: `fitgirl`.
- Um único arquivo distribuível em `dist/` para o usuário final.
- Código-fonte interno organizado como pacote sob `src/`.
- Testes somente sob `tests/`; ferramentas de desenvolvimento somente sob
  `tools/`; evidências somente sob `evidence/`; documentação somente sob `docs/`
  ou arquivos canônicos claramente nomeados.
- A raiz não deve conter vários `.py`/`.sh` que pareçam entrypoints concorrentes.
- O backend, monitor e verificador devem ser detalhes internos, não comandos
  concorrentes visíveis ao usuário.

## Reestruturação incremental do código-fonte

A estrutura alvo acordada está em [docs/REESTRUTURACAO.md](docs/REESTRUTURACAO.md).
Ela organiza o pacote em `cli/`, `planning/`, `execution/`, `verification/` e
`platform/`, com `translations.py` e `script_flow.py` como nomes escolhidos.
A migração deve ocorrer em pequenas etapas com uma responsabilidade por função
e por módulo, preservar comportamento e compatibilidade em cada estado
intermediário e validar testes e uso real do CLI quando aplicável. O assistente
prepara cada etapa, sugere um nome de commit em português e avisa o usuário;
somente o usuário cria o commit local atômico, sem push.
Ao relatar cada etapa, informar também o progresso global como percentual das
23 etapas conceituais listadas em `docs/REESTRUTURACAO.md`.

Um atalho futuro de ambiente gráfico pode abrir um terminal e executar
`fitgirl`; isso não cria uma interface gráfica do instalador nem altera o
requisito de um único comando e artefato público.

## Restrições de segurança e publicação

- Não executar `setup.exe`.
- Não publicar payloads proprietários extraídos de repacks.
- Não incorporar Wine privado, QuickSFV ou outros binários sem licença de
  redistribuição e fonte correspondente revisadas.
- Origem é somente leitura; destino e scratch são explícitos.
- Alterações destrutivas exigem staging, validação e rollback.
- O jogo deve ser extraído fora de qualquer prefixo Wine. O prefixo serve
  somente aos codecs e não configura a execução do jogo. Oferecer destinos
  genéricos e campo de caminho completo personalizado, sem depender de mounts
  específicos da máquina de desenvolvimento.
- Nunca usar `/tmp` ou `/tmp/opencode` para novos arquivos de trabalho. Builds,
  testes e logs de desenvolvimento devem usar `.work/` no projeto; instalações
  reais usam seu scratch persistente no filesystem de destino.

## Estado atual resumido

- O entrypoint público é `fitgirl`; os módulos internos ficam em `src/`.
- A implementação ainda é híbrida: Python, Bash e helper C/PE32.
- O comportamento está validado em FM7, Mirage 7 e The Darkness 2.
- O artefato único é gerado em `dist/fitgirl`; o build recusa documentação
  operacional desatualizada.
- O gerador recupera volumes, destinos, ordem, condições, payload temporário,
  pós-processamentos e hashes por IR/CFG conservador. Fluxos não comprovados
  continuam bloqueados como `draft/review_required`.
