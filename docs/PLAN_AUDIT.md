# Auditoria de planos

## O que existe hoje

`src/fitgirl_installer/plan_audit.py` compara um candidato com o ISS, o
disassembly IFPS e os hashes de origem registrados. O fluxo automático de
análise grava `plan-audit.json` ao gerar ou reutilizar o cache de um setup.

O relatório verifica:

- hashes de ISS, disassembly e `CompiledCode.bin`;
- reprodução byte a byte do disassembly, executando novamente o disassembler
  sobre o `CompiledCode.bin` vinculado;
- cobertura e sequência das chamadas mutantes reconhecidas;
- omissões, duplicatas e ações sem correspondência;
- argumentos, destinos, filtros, condições e escopos de rollback;
- componentes e inventários de payload;
- presença e posição da verificação final;
- alvos de controle não resolvidos e disassembly não analisável;
- ordens de ações alcançáveis por procedimento, com ciclos e truncamento
  explícitos, sem confundir ordem textual com ordem única de execução;
- enumeração global limitada por chamadas internas diretas; mostra limites por
  procedimento, mas não remove `review_required`.

Ferramenta interna de desenvolvimento:

```bash
python3 tools/audit-plan.py \
  --manifest caminho/manifest.draft.json \
  --iss caminho/innounp/install_script.iss \
  --compiled caminho/innounp/embedded/CompiledCode.bin \
  --disassembly caminho/CompiledCode.disassembly.txt \
  --output .work/plan-audit.json \
  --disassembler ~/.local/share/fitgirl-installer/tools/pascalscript
```

O retorno é zero somente quando não há divergências, com estado
`MATCH_REVIEW_REQUIRED`. Divergências produzem `MISMATCH` e retorno 1.
A auditoria não altera o candidato nem remove `draft/review_required`.

## Limites importantes

Essa é uma auditoria de **consistência**, não uma prova independente de
equivalência ao bytecode. A reconstrução de argumentos compartilha funções do
planner; um defeito comum aos dois pode passar despercebido. A reprodução agora
demonstra que o texto auditado saiu daqueles bytes com a ferramenta configurada,
mas não constitui um segundo decoder independente. Ordem estática das instruções não equivale à ordem de
execução em condições, loops e chamadas entre procedimentos.

A validação de 2026-11-04 provou, com escopo limitado, a ordem das chamadas mutantes reconhecidas nos drafts de Star Trucker, Children of Morta e Subnautica: todas ficam em `CurStepChanged`; após dobrar somente o padrão local `assign variável, 0/1` seguido por `if`/`if not` da mesma variável, o CFG desse procedimento tem apenas arestas para endereços posteriores. Os endereços das 19, 43 e 28 chamadas coincidem com as sequências dos respectivos manifests. Não há `call-var` nem alvo CFG não resolvido nesses disassemblies. Evidência e hashes: `evidence/interprocedural-action-order-2026-11-04.json`.

Isso prova a ordem relativa das ações catalogadas dentro desses três procedimentos, não qual guarda será verdadeira, a correspondência semântica dos valores de evento, nem efeitos externos não catalogados. `review_required` permanece ativo. Ainda faltam interpretação independente das guardas/condições, equivalência semântica e ampliação do corpus real.
As ferramentas foram recuperadas em diretório persistente; consulte
[`THIRD_PARTY.md`](THIRD_PARTY.md) e `tools/bootstrap-analysis.sh`. Star Trucker,
Children of Morta e Subnautica já tiveram ISS/IFPS extraídos e auditados. Nenhum
desses resultados autoriza liberar automaticamente um plano.

## Prova semântica parcial

A análise agora reconhece uma forma estreita de guarda de evento em `CurStepChanged`: comparação direta do parâmetro `s-1` com ordinal literal, `set-flag not` e `flag-goto`. O ordinal `2` corresponde a `ssPostInstall`: a enumeração está declarada nessa ordem no código-fonte do Inno Setup, enumerações Pascal usam ordinais começando em zero por padrão, e a documentação oficial descreve o momento desse evento. A polaridade do salto foi conferida no runtime PascalScript do próprio Inno Setup.

Nos três drafts vinculados ao bytecode, todas as 19, 43 e 28 ações catalogadas ficam dentro do ramo `ssPostInstall`. As 7, 10 e 6 alterações INI protegidas por checkbox têm guardas `use2gb` recuperadas. A construção da máscara de componentes e os índices `CurComponent` se alinham estruturalmente em todas as 3, 7 e 6 chamadas de extração de cada candidato. A DLL exata agora foi extraída dos três setups e é byte-idêntica (SHA-256 registrado na evidência). A análise estática do export `ISArcExtract` confirma que `CurComponent` é testado contra três máscaras de 32 bits recebidas na inicialização: índice 0 é incondicional; os índices 1–96 consultam o bit correspondente. Se não selecionado, o export retorna sucesso sem entrar no fluxo de extração. Isso fecha a correspondência semântica dos opcionais nesses binários.

Os três setups amostrados carregam a mesma `ISDone.dll` (SHA-256 registrado na evidência). A inspeção estática reconstruiu os efeitos dos cinco exports solicitados. `ISDoneInit` valida e retém o caminho `records.inf`, prepara estado global, máscaras de seleção, estado de callback/UI e contadores; inicializa também o byte de `FileSearchInit` e o byte de retorno de `Exec2`. `PrecompInit` valida o seletor de precomp e grava `[Precomp] Memory` e `TempPath` em `CLS.ini` via `WritePrivateProfileStringA`. `FileSearchInit` grava um byte global e retorna sucesso; nenhuma leitura desse byte foi encontrada no módulo inteiro. `ChangeLanguage` lê e interpreta o INI de idioma para atualizar strings locais, mostrando erro se o arquivo faltar ou falhar a leitura. `ISDoneStop` limpa o texto da janela e libera estado; sob uma guarda específica pode apagar o `records.inf` retido, se ele passou a existir e as demais flags de cleanup forem zero.

Em `Exec2`, o slot de ponteiro `0x45C504` aponta para o byte global `0x45DDAA`. `ISDoneInit` e `Exec2` o zeram; `Exec2` o define como 1 quando `CreateProcessA` falha, consulta-o na lógica de término e devolve-o ao chamador. Busca completa de referências na DLL não encontrou outros escritores internos. Nos três bytecodes, o ponteiro de callback de `ISDoneInit` é `PROGRESSCALLBACK`: a rotina só atualiza barra, taskbar e rótulos e não chama `Exec2`; cada setup tem uma única chamada `Exec2`, no ramo `CurStepChanged(ssPostInstall)`. Assim, o callback IFPS registrado não escreve essa flag. `Exec2` também bombeia mensagens Win32 com `DispatchMessageA`; reentrada iniciada por um procedimento nativo da janela permanece fora do escopo estático.

A auditoria estática solicitada está concluída para os cinco exports e os três bytecodes exatos. O auditor bloqueia os três efeitos externos ausentes do plano nativo: tentativa de desinstalação silenciosa, gravação de `CLS.ini` por `PrecompInit` e possível remoção de `records.inf` por `ISDoneStop`. Os drafts de Star Trucker, Children of Morta e Subnautica persistem esses bloqueios; o CLI os recusa antes da instalação. As limitações finais são reentrada possível por procedimento nativo da janela e resultados em runtime da resolução de caminhos e guardas de cleanup. Não foi executada a DLL nem o instalador. O estado final é `STATIC_AUDIT_COMPLETE_WITH_RUNTIME_LIMITS`, sem equivalência total alegada. Escopo, hashes, argumentos e endereços: `evidence/semantic-guard-audit-2026-11-04.json`.

## Compatibilidade do host

A checagem global antes de prompts/operações exige Linux x86-64, glibc 2.38+, Python 3.12+, `libstdc++`, `libgcc_s` e comandos de sistema usados pelo launcher/backend. `fitgirl doctor` mostra os valores encontrados. O limite 2.38 foi extraído dos símbolos requeridos pelos binários Wine/`unarc` fixados. Debian 13, Ubuntu 24.04 LTS e CachyOS rolling foram exercitados; outros sistemas não são promovidos a suportados apenas por satisfazerem os mínimos. O gate não substitui a análise de bibliotecas carregadas dinamicamente.

Evidência completa, com hashes e limites: `evidence/semantic-guard-audit-2026-11-04.json`. Fontes de referência: [declaração oficial de `TSetupStep`](https://github.com/jrsoftware/issrc/blob/main/Projects/Src/Shared.SetupSteps.pas), [eventos do Inno Setup](https://jrsoftware.org/ishelp/topic_scriptevents.htm), [ordinais de enumeração Pascal](https://docwiki.embarcadero.com/RADStudio/Athens/en/Simple_Types) e [runtime PascalScript do Inno Setup](https://github.com/jrsoftware/issrc/blob/main/Components/UniPs/Source/uPSRuntime.pas).

## Evidências

Em `evidence/plan-audit-2026-11-01/`:

- `directive-report.json`: candidato real com zero divergências, ainda sujeito
  a revisão semântica;
- `directive-mutations.json`: nove variantes adulteradas detectadas;
- `tests.log`: suíte automatizada da revisão.

Em `evidence/compiled-binding-2026-11-02/`, Star Trucker, Children of Morta e
Subnautica foram redesmontados a partir dos respectivos `CompiledCode.bin`; os
três resultados coincidiram byte a byte, com zero divergências de plano. O estado
continua `MATCH_REVIEW_REQUIRED` porque isso vincula os artefatos, não prova a
semântica de todos os caminhos.

A enumeração conservadora encontrou 2.177 sequências em Star Trucker e atingiu
o limite de 4.096 em Children of Morta e Subnautica; os três possuem ciclo no
procedimento relevante. Isso confirma objetivamente que a prova completa de
condições e ordem ainda não pode ser substituída por uma lista linear.

Arquivos de trabalho e logs novos ficam em `.work/`, nunca em `/tmp`.
