# Política de integração Linux/Windows

O objetivo público continua sendo extrair e validar o jogo sem executar
`setup.exe`. Wine ou Proton instalado pelo usuário funciona como ABI para DLLs,
codecs e pós-processamentos auditados; não é escolhido como runner do jogo nem
incluído na release.

Após uma instalação concluída, o instalador grava `integration-report.json` no
scratch. O relatório inventaria executáveis candidatos, redistribuíveis e
arquivos `.reg`, sem modificar a árvore validada.

Política atual:

- DirectX, VC++, .NET, PhysX e outros redistribuíveis são preservados, mas nunca
  executados automaticamente;
- arquivos de registro são inventariados, mas nunca importados;
- atalhos não são criados, pois configurar um runner está fora do escopo;
- nenhum executável encontrado por heurística é iniciado automaticamente;
- a validação MD5 permanece independente de QuickSFV e desses componentes.

Existem relatórios empíricos de Directive 8020, Star Trucker e Mirage 7 em
`evidence/integration-policy-2026-11-02/`. A seleção do executável é apenas uma
lista ordenada de candidatos; não comprova jogabilidade.

Não existe etapa posterior de validação do runner. Falha ou sucesso de
Proton/Wine não altera o resultado da instalação e não autoriza reutilizar o
Wine de codecs para abrir o jogo.
