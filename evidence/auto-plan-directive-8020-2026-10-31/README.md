# Plano automático — Directive 8020

Execução real do comando público contra um setup sem manifesto conhecido.

- setup SHA-256: `6a62f8e753a1b7f21718f3605d366e1d2d895563f8d83dc5429b4c9eb0015cc9`;
- resultado atual: 44 etapas recuperadas — 14 `ini-write`, 13 `isexec`, oito
  extrações, sete `delete-tree`, um `delete-file` e uma verificação;
- segurança: instalação recusada porque o manifesto permanece
  `draft/review_required`;
- `manifest.draft.json` inclui hashes do ISS, IFPS, disassembly, `innounp` e
  disassembler usados;
- `public-command.log` preserva o resultado observado pelo usuário;
- `control-flow-summary.json` preserva métricas do CFG, predicados constantes e
  a ausência de alvos de controle não resolvidos, além do bitmask de seis
  componentes comprovado estruturalmente;
- `public-command-ir.log` registra a recusa após gerar/migrar IR e CFG.
- `payload-materialize.log` registra os 39 arquivos temporários reais;
- `payload-ini-resume.log` registra as 14 mutações e a retomada dos hashes;
- `application-payload.log` registra os quatro arquivos `_Redist`;
- `rollback-plan.log` registra a compilação versão 9 e a recusa segura;
- `transaction-tests.log` registra a suíte com rollback, quarentena e retomada.
- `isexec-smoke.log` registra execução real e transacional de `fnr.exe` e
  `FlushFileCache.exe` via Wine.

Cobertura atual: 43/43 chamadas mutantes, 41/41
`ExtractTemporaryFile`, 39 arquivos temporários únicos, quatro entradas `{app}` e
13/13 `isexec` com `rollback_paths`. Os snapshots de árvore completa de
`build01.bat` e `x5n.exe` ainda exigem medição real; por isso o plano permanece
bloqueado.

O ISS, o bytecode e o disassembly completos permanecem somente no cache local;
não foram duplicados nesta evidência por conterem material do instalador.
