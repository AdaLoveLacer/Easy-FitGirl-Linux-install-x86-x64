# Pendências operacionais

> ARQUIVO GERADO. Não edite diretamente. Atualize
> `status/project-status.json` e execute `./tools/sync-docs.py --write`.

Última atualização declarada: 2026-11-05  
Suíte automatizada descoberta: **104/104 testes**.

## 1. Monitoramento da ordem em produção

Estado: **IMPLEMENTADO — VERIFICAÇÃO AUTOMATIZADA PENDENTE**

- [x] Registrar no journal cada etapa iniciada e concluída, validar ordem contra as etapas selecionadas e interromper antes de despachar uma etapa fora de ordem.
- [x] Ao detectar divergência, preservar diagnóstico JSON sanitizado no scratch com etapa esperada/observada, hashes do setup/plano e eventos recentes; pedir ao usuário que envie o arquivo ao suporte, sem envio automático.
- [x] Migrar journals antigos usando o prefixo concluído já registrado e validar compatibilidade sem descartar retomadas existentes.

## 2. Directive 8020 real

Estado: **CONCLUÍDO — PLANO REVISADO**

- [x] Materializar e auditar os 39 arquivos temporários e os quatro arquivos `_Redist`.
- [x] Isolar o payload runtime para não sobrescrever `arc.ini` e `CLS.ini` auditados.
- [x] Confirmar `FICLONE` no Btrfs do destino para snapshots conservadores.
- [x] Corrigir o prefixo de `fg-07.bin` com a opção nativa FreeArc `-apwork`, validada em extração real.
- [x] Recuperar as quatro mutações INI e fnr após reconstrução legada do payload, preservando backup e journal.
- [x] Recusar reconstrução automática de payload divergente quando há etapas concluídas; tolerar arquivos auxiliares adicionais na retomada.
- [x] Tratar retorno do FART como contagem, condicionado à contagem prevista e à validação byte a byte dos resultados.
- [x] Concluir build01.bat, patch x5n e extração de inner.fgpack após recuperação da queda de energia.
- [x] Tratar cmd del literal com escopo comprovado como exclusão nativa idempotente e reversível.
- [x] Concluir as oito etapas de extração no destino descartável.
- [x] Concluir os 13 pós-processamentos e as oito remoções; transações finalizadas após MD5.
- [x] Validar `_Redist/fitgirl.md5`: 289/289 arquivos, 38.194.436.754 bytes, zero ausentes e divergências.
- [x] Recuperar a etapa build01.bat interrompida por queda de energia usando o snapshot e o journal.
- [x] Encerrar no gate correto: extração integral, estrutura final e MD5 289/289 sem ausências ou divergências; inicialização está fora do escopo.

## 3. QuickSFV x64

Estado: **DOCUMENTADO — REDISTRIBUIÇÃO NÃO AUTORIZADA**

- [x] Validar QuickSFV 2.36 x64 no FM7: 4.416 OK, zero ruins e zero ausentes.
- [x] Preservar a edição PE32 e impedir downgrade durante retomada.
- [x] Cobrir instalação, restauração e `dry-run` com testes.
- [x] Documentar uso, origem externa e limitações de licença; manter fora do artefato até obter termos explícitos de redistribuição.

## 4. Compatibilidade genérica

Estado: **PROVA ESTÁTICA AMPLIADA — EQUIVALÊNCIA COMPLETA PENDENTE**

- [x] Implementar auditoria automática de consistência entre plano, ISS, disassembly IFPS e hashes do CompiledCode.bin.
- [x] Validar auditoria no Directive real e rejeitar nove variantes adulteradas do plano, mantendo revisão semântica obrigatória.
- [x] Redesmontar automaticamente `CompiledCode.bin` e exigir reprodução byte a byte do disassembly; comprovado em Star Trucker, Children of Morta e Subnautica.
- [x] Enumerar ordens intraprocedurais conservadoras: Star Trucker 2.177 sequências; Children of Morta e Subnautica truncados em 4.096; todos com ciclo e revisão obrigatória.
- [x] Restaurar innounp 0.50 e disassembler IFPS persistentes, com fontes, commit, patch e hashes registrados.
- [x] Analisar novos setups Star Trucker, Children of Morta e Subnautica: cobertura reconhecida 19/19, 43/43 e 28/28; auditoria consistente, ainda exige revisão.
- [x] Implementar combinação nativa transacional de fitgirl.md5 e addons, preservando os manifestos originais.
- [x] Ampliar ensaios reais com Star Trucker core e bônus: 224/224 arquivos MD5 válidos; não implica cobertura de famílias arbitrárias.
- [x] Cobrir mais idiomas, opcionais ausentes e pós-processamentos; The Darkness 2 validado em inglês, russo, espanhol, alemão, francês, italiano e japonês, com core 146/146 e addon 16/16 sem ausências ou divergências
- [x] Alegação de compatibilidade universal permanece removida; somente setups/planos auditados e empiricamente instalados são suportados.
- [x] Provar a ordem das chamadas mutantes reconhecidas em Star Trucker (19), Children of Morta (43) e Subnautica (28): todas em CurStepChanged, sequências de manifest coincidentes, CFG sem ciclos após dobra conservadora de condição constante; drafts continuam review_required. Evidência em evidence/interprocedural-action-order-2026-11-04.json.
- [x] Provar guardas de evento/checkbox e semântica da máscara de seleção nos três drafts; analisar ISExec e Exec2 pela DLL exata: CurComponent respeita a máscara, ISExec retorna false para componente ignorado e falha e Exec2 aguarda processo e devolve flag de estado, não exit code. Evidência em evidence/semantic-guard-audit-2026-11-04.json; helpers e equivalência completa seguem pendentes.
- [x] Concluir a auditoria estática dos efeitos de ISDoneInit, PrecompInit, FileSearchInit, ChangeLanguage e ISDoneStop; inventariar escritores internos da flag Exec2 e auditar os callbacks IFPS dos três setups. Concluído para a DLL hash c652b4b5…; progress callback não chama Exec2. Reentrada por janela nativa e resultados runtime registrados como limites; drafts continuam bloqueados pelos três efeitos externos. Evidência: evidence/semantic-guard-audit-2026-11-04.json.
- [x] Recusar planos gerados cujo fluxo interprocedural não foi provado: draft/review_required é bloqueado antes da instalação; cobertura em tests/test_plan_generator.py e tests/test_plan_audit.py.
- [x] Adicionar verificação global de compatibilidade: Linux x86-64, glibc 2.38+, Python 3.12+, libstdc++/libgcc_s e comandos essenciais; fornecer `fitgirl doctor` sem espalhar tratamento por try/catch.
- [x] Bloquear o efeito Exec2({uninstallexe}, /VERYSILENT): a auditoria agora reporta MISMATCH, persiste semantic_blockers no draft e o CLI recusa antes da instalação. Aplicado aos drafts existentes de Star Trucker, Children of Morta e Subnautica.

## 5. Compatibilidade do host Linux

Estado: **IMPLEMENTADO — MATRIZ EMPÍRICA AINDA LIMITADA**

- [x] Documentar arquitetura, glibc mínima, Python, bibliotecas ELF e ferramentas de sistema requeridas, com Debian 13, Ubuntu 24.04 e CachyOS como ambientes verificados.
- [ ] Ampliar validação de startup em distribuições adicionais e verificar bibliotecas Wine carregadas dinamicamente e codecs que dependem delas.

## 6. Star Trucker — validação entre discos

Estado: **CONCLUÍDO — PLANO REVISADO**

- [x] Manter volumes de origem no disco de origem e preparar scratch e destino no disco de destino; não usar o SSD que não foi usado.
- [x] Validar os três volumes por MD5; limite de saída 6.633.291.776 bytes e reserva com margem 24.004.001.792 bytes, com 104.061.636.608 bytes livres no disco de destino.
- [x] Corrigir loop do wrapper Razor causado por caminho temporário longo: drive curto para scratch, sem mover dados entre discos.
- [x] Concluir os três volumes e combinar os manifestos do core e bônus.
- [x] Validar fitgirl.md5 combinado com bonus.addon: 224/224 arquivos, 6.632.164.425 bytes, zero ausentes e divergências.
- [x] Registrar o resultado empírico sem promover rascunhos desconhecidos a compatibilidade universal.
- [x] Encerrar no gate correto: extração integral, estrutura final e MD5 224/224 sem ausências ou divergências; inicialização está fora do escopo.

## 7. Desempenho e recursos

Estado: **CONCLUÍDO**

- [x] Calibrar progresso e ETA no `fg-06` do FM7 e no `fg-01` do Mirage: pós-leitura explícita e ETA desconhecida sem falso zero.
- [x] Sinalizar releituras internas por PID sobrevivente e exibir RSS/PSS, picos e afinidade dos workers no monitor.
- [x] Incluir rzw/rz e nomes sem .exe no monitor; filtrar por prefixo Wine e distinguir CPU ocupada de avanço comprovado.
- [x] Confirmar afinidade real 0-1 em helper, SREP, Magic2 e XTool no fg-01 do Mirage 7.
- [x] Medir Mirage fg-01: automático 4.017/3.946 MiB RSS/PSS; SREP 2.048, 4.180/4.106; SREP 4.096, 4.181/4.107; parâmetro SREP não é teto global.
- [x] Validar pausa e retomada do grupo Wine sob carga real: 20 s em estado T com deltas zero; retomada concluiu MD5 238/238.
- [x] Validar aplicação real do teto cgroup MemoryMax: systemd-run --scope com 768 MiB expôs memory.max=805306368 bytes; o teto pode causar OOM/retomada, não é promessa de estabilidade. Evidência em evidence/resource-controls-2026-11-04.json.

## 8. Runtime de codecs e interface portátil

Estado: **VALIDADO EM DEBIAN E UBUNTU**

- [x] Release sem o runtime Wine FitGirl privado, cuja correspondência completa de fontes/patches não foi comprovada; o pacote exige Wine/Proton do usuário e documenta essa dependência.
- [x] Preparar runtime em XDG_DATA_HOME com lock, staging, extração segura e publicação atômica; recusar corrupção sem sobrescrever dados existentes.
- [x] Manter Wine fora do menu: a release usa Wine/Proton instalado pelo usuário; provisionamento privado fica restrito ao desenvolvimento local.
- [x] Listar cada disco local montado com uma pasta Games, mesmo ainda inexistente, além de caminho completo personalizado; recusar jogo dentro do prefixo Wine.
- [x] Validar primeira execução do artefato completo e concluir Mirage 7: 238/238 arquivos, 2.500.148.966 bytes, zero ausentes e divergências, após recuperar o manifesto sem reextração.
- [x] Explicar limites avançados, separar threads BZip3 de afinidade global, impor faixas derivadas de CPU/RAM/cgroup e detectar QuickSFV x64 aprovado sem pedir caminho.
- [x] Isolar journals de retomada pelo nome exato do destino para evitar colisão entre instalações irmãs do mesmo repack.
- [x] Validar provisionamento do Wine e ligações ELF do innoextract em Debian 13 e Ubuntu 24.04 x86-64; arquitetura adicional não é anunciada nem aceita. Evidência em evidence/runtime-portability-2026-11-03/containers.json.
- [x] O runtime Wine FitGirl privado foi excluído do pacote de publicação porque fontes/patches correspondentes não estavam verificáveis.

## 9. Integração Linux/Windows

Estado: **CONCLUÍDO — SELEÇÃO INTERATIVA VALIDADA**

- [x] Mostrar tamanho compactado na abertura, tamanho dos componentes selecionados no resumo e estimativa de espaço declarada no ISS quando disponível, sem executar codecs.
- [x] Definir e registrar política por instalação: preservar redistribuíveis sem executá-los, não importar registro e usar Wine/Proton do sistema apenas como ABI de codecs.
- [x] Não criar atalhos, importar registro ou configurar runner; essas ações de execução do jogo estão fora do escopo.
- [x] Validar seleção interativa no FM7 real com o opcional 4K; confirmar política de não executar redistribuíveis e cancelar antes de iniciar a instalação; evidência em evidence/menu-selection-2026-11-03/forza-motorsport-7.json.

## 10. Publicação

Estado: **PUBLICADO EM origin/main — 4bfc238**

- [x] Fechar a revisão de redistribuição: fontes/avisos dos componentes mantidos foram incluídos; Wine FitGirl e QuickSFV sem grant explícito foram retirados do artefato. Ver docs/THIRD_PARTY.md e third_party/.
- [x] Auditar o pacote de publicação: sem payloads de jogos, volumes FitGirl, DLLs de codec, QuickSFV ou Wine FitGirl; inventário em THIRD-PARTY-BINARIES.json.
- [x] Fixar origem/hash e incluir licenças, avisos e fontes correspondentes de innoextract, unarc, liblzma e helper; Wine FitGirl e QuickSFV não são empacotados.
- [x] Gerar pacote local com build standalone, inventário de binários, fontes correspondentes, avisos e SHA-256; artefato em dist/FitGirlInstaller-Linux-x86_64.zip.
- [x] Fixar commits/releases, checksums, fontes e instruções de build dos componentes de terceiros mantidos; THIRD-PARTY-BINARIES.json inventaria os hashes exatos do pacote.
- [x] Revisar nomes e arquivos para publicação; manter .work/ e dist/ ignorados pelo Git.
- [x] Inicializar Git localmente e preparar o pacote com fontes/licenças e checksum. Não foi configurado remoto nem enviado/publicado o artefato.
- [x] Aplicar 0BSD ao material original do projeto; LICENSE criado, limites de terceiros explicitados e aviso incluído no pacote. A licença não relicencia dependências de terceiros.
- [x] Publicar a atualização licenciada e validada em origin/main; commit 4bfc238 confirmado no remoto em 2026-11-04.

## 11. Limpeza final

Estado: **CONCLUÍDO**

- [x] Concluir todas as validações ativas antes de remover dados de diagnóstico; matriz do The Darkness 2 e suíte 95/95 concluídas.
- [x] Preservar instalações validadas, evidências, manifests e journals necessários; cinco targets finais do The Darkness 2 e evidências mantidos.
- [x] Inventariar e remover targets parciais, arquivos vazios, stagings, prefixos e caches obsoletos; 25 entradas removidas.
- [x] Confirmar que nenhum processo usa os caminhos e registrar o espaço recuperado; 19,12 GiB liberados em evidence/cleanup-2026-11-03.json.

## 12. Interface bilíngue

Estado: **IMPLEMENTADA — PORTUGUÊS E INGLÊS**

- [x] Perguntar o idioma no início de cada execução interativa e propagar a escolha para prompts, interface, erros e monitoramento; FITGIRL_LANGUAGE permite automação.
- [x] Publicar README.md em inglês e README.pt-BR.md em português, com conteúdo conciso e links entre as versões.
- [x] Incluir licença 0BSD e os dois READMEs no ZIP standalone, mantendo avisos de componentes de terceiros separados.

## 13. Interface simplificada, teste real e pacote de teste

Estado: **CONCLUÍDO — INSTALAÇÃO REAL VALIDADA**

- [x] Reorganizar o menu TTY em quatro etapas, reduzir a densidade de texto e compactar o monitor ao vivo sem descartar logs detalhados.
- [x] Executar o repack Mirage 7 escolhido pelo usuário no destino selecionado; concluir dois volumes e a etapa de verificação.
- [x] Validar o resultado real: 238/238 arquivos MD5, 2.500.148.966 bytes, zero ausentes ou divergentes.
- [x] Criar ZIP autocontido com executável, dependências compartilhadas do innoextract, instruções e SHA-256; conferir listagem e integridade do ZIP.
- [x] Validar ZIP atualizado em container Debian limpo e confirmar inicialização do runtime Wine e do innoextract.

## Baseline validado

- FM7 1080p: 4.416/4.416 arquivos válidos.
- FM7 4K: 35 vídeos opcionais preservados, 36 arquivos 2160p finais e backup 1080p preservado.
- Mirage 7: 238/238 arquivos válidos.
- The Darkness 2: sete idiomas validados; cada alvo teve core 146/146 e addon 16/16 sem ausências ou divergências, incluindo pós-processamento X5.
- Directive 8020 (plano revisado): instalação integral e retomada após queda de energia concluídas; 289/289 arquivos MD5 válidos, zero ausentes e divergências. Gate final satisfeito.
- Star Trucker core e bônus (plano revisado): 224/224 arquivos MD5 válidos no manifesto combinado, zero ausentes e divergências. origem e destino em discos distintos; gate final satisfeito.
- Artefato final após validação dos sete idiomas do The Darkness 2: dist/fitgirl SHA-256 cbc1790b1ce5b4366854179c957fa5c9c4ac896100a728daec94f1bd51ba78ce; suíte 95/95 aprovada. Limpeza final: 19,12 GiB liberados, cinco targets finais preservados.
- Menu interativo do FM7 validado com seleção do opcional 4K; instalação cancelada antes de qualquer escrita no destino. QuickSFV x64 detectado automaticamente em instalação local existente.
- Build standalone repetido a partir das entradas fixadas com SHA-256 idêntico ao baseline; auditoria do artefato não encontrou payloads de jogo, volumes, DLLs de codec ou QuickSFV.
- Interface terminal simplificada e teste real do Mirage 7 concluído: 238/238 arquivos MD5 válidos, zero ausentes/divergentes; ZIP de teste autocontido em dist/FitGirlInstaller-Linux-x86_64.zip, com instruções e checksum.
- Runtime standalone iniciou Wine 11.14 e innoextract em Debian 13 e Ubuntu 24.04 x86-64 após empacotar dependências Boost/zlib/xz/bzip2/zstd; sem extração completa de repack nos containers.
- Após simplificação do terminal e empacotamento das dependências do innoextract: suíte 96/96 aprovada; ZIP atualizado e runtime iniciado em Debian 13 e Ubuntu 24.04 x86-64.
- Revisão do status em 2026-11-04: cgroup MemoryMax observado em escopo systemd real (768 MiB); afinidade Mirage fg-01 confirmada em 96 amostras para os quatro workers observados. Nenhuma extração completa foi executada sob MemoryMax reduzido.
- Ordem de chamadas mutantes reconhecidas validada em três drafts: Star Trucker 19/19, Children of Morta 43/43, Subnautica 28/28; todas em CurStepChanged, fluxo acíclico e sequência de manifest coincidente. Guardas semânticas permanecem pendentes e drafts continuam bloqueados para revisão.
- O journal de instalação agora registra a ordem runtime das etapas e bloqueia avanço fora do plano; divergências geram relatório sanitizado em scratch/reports e solicitação para envio voluntário ao suporte. Verificação automatizada desta alteração ainda pendente.
- Guardas de evento/checkbox analisadas em Star Trucker, Children of Morta e Subnautica: ações reconhecidas 19/19, 43/43 e 28/28 protegidas por ssPostInstall; opções use2gb e mapa de bits de seleção confirmados estruturalmente. Contrato e efeitos de seis chamadas externas ISDone.dll por setup continuam sem prova independente. Evidência em evidence/semantic-guard-audit-2026-11-04.json.
- Em 2026-11-04: análise estática da ISDone.dll idêntica nos três setups confirmou máscara CurComponent, ISExec retorna false tanto para componente ignorado quanto para falha e Exec2 aguarda por GetExitCodeProcess, retorna flag definida quando CreateProcessA falha, e os chamadores ignoram esse retorno; fluxo IFPS pode tentar desinstalação silenciosa após ISExec falso; documentação atualizada em evidence/semantic-guard-audit-2026-11-04.json. A checagem global de host e fitgirl doctor foram implementados; glibc mínima 2.38 inferida do maior símbolo requerido por binários fixados. Evidência em evidence/platform-compatibility-2026-11-04.json. Matriz dinâmica ainda pendente.
- Análise estática aprofundada da ISDone.dll: Exec2 espera o processo, mas não devolve seu exit code; nos três drafts, ISExec falso mantém a flag de erro e o ramo ssPostInstall tenta iniciar {uninstallexe} /VERYSILENT, ignorando o retorno de Exec2. Efeito identificado como ação externa de alto impacto ausente do plano nativo; drafts mantidos em revisão. Evidência em evidence/semantic-guard-audit-2026-11-04.json.
- Correção de bloqueio semântico: chamadas Exec2 para {uninstallexe} /VERYSILENT agora geram efeito crítico e MISMATCH; semantic_blockers são persistidos e recusados pelo CLI. Atualizados os três drafts existentes no cache. Não se executou nenhum instalador. Ver evidence/semantic-guard-audit-2026-11-04.json.
- Preparação de publicação em 2026-11-04: Wine privado e QuickSFV removidos do pacote; fontes/licenças de innoextract, unarc e liblzma incluídas, hashes dos binários inventariados. Git inicializado localmente; pacote dist/FitGirlInstaller-Linux-x86_64.zip preparado e checksum verificado. Nenhum envio externo foi feito.
- Pacote de publicação final em 2026-11-04: SHA-256 f89cfd45fc64ec440cb4af9f5f83974b36b38fcc21f48bf052d931794d1a60f9, 15 arquivos, 2,125,782 bytes; executável standalone SHA-256 7bc921bd090b60e282273799117c046f94906dc3fed0ae8ff9a0cb757e27c578; source bundle SHA-256 bf7c25d394b38764d8a6b6228476643ddfdf0cfb3b3a34e16212ea0244e2edef. Hashes e fontes registrados em evidence/release-preparation-2026-11-04.json.
