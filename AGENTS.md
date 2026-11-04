# Regras locais do projeto

- Nunca usar `/tmp`, nem `/tmp/opencode`, para novos arquivos, logs, prefixos,
  builds ou testes. Usar `.work/` dentro do projeto para desenvolvimento e o
  scratch persistente da instalação para execução real.
- Antes de executar testes Python, criar `.work/tmp` e exportar `TMPDIR` com seu
  caminho absoluto. Assim `tempfile` também respeita a política.
- Não mover ou apagar dados existentes apenas para cumprir essa regra.
- Atualizar `status/project-status.json`, sincronizar com
  `python3 tools/sync-docs.py --write` e verificar com `--check` ao concluir ou
  bloquear trabalho. Relatos históricos não devem ser reescritos como estado atual.
