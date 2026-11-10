# Ampliação do corpus — 01/11/2026

ISS e IFPS extraídos sem executar o setup de três repacks ainda não validados
integralmente nesta fase:

| Repack | Etapas | Chamadas mutantes reconhecidas | Auditoria |
|---|---:|---:|---|
| Star Trucker | 20 | 19/19 | MATCH_REVIEW_REQUIRED |
| Children of Morta | 44 | 43/43 | MATCH_REVIEW_REQUIRED |
| Subnautica | 29 | 28/28 | MATCH_REVIEW_REQUIRED |

Cobertura completa não prova semântica universal. Children of Morta e Subnautica
mantêm pós-processamentos sem escopo de rollback comprovado e não foram
liberados para instalação. Star Trucker teve revisão isolada: quatro INIs,
condições `use2gb`, FlushFileCache, volumes core/bônus, remoções confinadas e
combinação nativa transacional de manifestos.

Os três volumes do Star Trucker passaram no MD5 de origem. A listagem FreeArc
informou limite superior arredondado de 6.633.291.776 bytes de saída. A reserva
conservadora (dobro + 10 GiB) é de 24.004.001.792 bytes, contra
104.061.636.608 bytes livres medidos no destino.

Origem: `/mnt/SOURCE_DISK/Torrent/Games/Star Trucker [FitGirl Repack]`.
Destino novo: `/mnt/DESTINATION_DISK/Games/Star Trucker native validation`.
Scratch: `/mnt/DESTINATION_DISK/Games/.fitgirl-work/star-trucker-native-validation`.

O SSD que não foi usado não foi usado como origem ou destino do jogo. A instalação
concluiu, incluindo bônus: **224/224 arquivos válidos**, zero ausentes, zero
divergências, 6.632.164.425 bytes calculados em 109,556 segundos. O manifesto
combinado, a base original e `bonus.addon` foram preservados. O journal ficou
inativo e sem transações pendentes. Inicialização do jogo não foi testada.

A retomada corrigiu o loop do wrapper Razor com drive curto para o scratch;
consulte `razor-longpath.log`, `razor-shortpath.log` e
`razor-loop-excerpt.log`. Evidências finais: `star-installation-success.log` e
`star-completed-install-state.json`.

O binário persistente do disassembler foi recompilado de fonte fixada, com 54
testes upstream aprovados. Seu adaptador reproduziu exatamente as 10.756 linhas
de instrução do cache Directive; diferenças de apresentação no restante do
texto não são tratadas como igualdade binária. Consulte `toolchain.json`.
