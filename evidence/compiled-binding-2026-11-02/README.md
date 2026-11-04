# Vinculação de CompiledCode.bin ao disassembly

O disassembler IFPS persistente foi executado novamente sobre o
`CompiledCode.bin` de Star Trucker, Children of Morta e Subnautica. Para os três
setups, a saída reproduzida coincidiu byte a byte com o disassembly usado pelo
planner e a auditoria encontrou zero divergências.

| Jogo | Reprodução binária | Auditoria |
|---|---:|---:|
| Star Trucker | idêntica | MATCH_REVIEW_REQUIRED |
| Children of Morta | idêntica | MATCH_REVIEW_REQUIRED |
| Subnautica | idêntica | MATCH_REVIEW_REQUIRED |

Os relatórios JSON preservam hashes e detalhes. Esta evidência elimina a lacuna
de proveniência entre binário e texto, mas usa o mesmo disassembler e não prova
condições, loops ou ordem interprocedural por caminho de execução.

`action-paths.json` enumera ordens intraprocedurais conservadoras sem desenrolar
loops. Star Trucker produziu 2.177 sequências e um ciclo. Children of Morta e
Subnautica atingiram o limite de 4.096 sequências e também possuem ciclo. Logo,
a ordem linear do disassembly não pode ser promovida a ordem única de execução.

`interprocedural-paths.json` amplia a mesma ideia para chamadas diretas a
procedimentos parseados nas entradas relevantes, com profundidade e limites de
quantas sequências recolher. Nos três setups, `INITIALIZEWIZARD` e
`CURSTEPCHANGED` permaneceram truncados; os resultados medem a fronteira, não
provam independentemente a semântica Pascal. Isso mantém planos desconhecidos em
revisão obrigatória.
