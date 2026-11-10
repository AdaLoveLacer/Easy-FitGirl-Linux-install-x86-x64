# Ferramentas persistentes de análise

Instalação local (não é outro instalador de jogos):

```bash
bash investigacao/tools/bootstrap-analysis.sh
```

O bootstrap fixa o commit do parser IFPS, aplica o patch de nomes de exports,
compila o adaptador CLI e executa os testes upstream. O download de innounp é
aceito apenas com os SHA-256 registrados. Tudo é preparado dentro de `.work/`;
nada é baixado para `/tmp`. Sem sudo.

Binários finais:

```text
~/.local/share/fitgirl-installer/tools/innounp.exe
~/.local/share/fitgirl-installer/tools/pascalscript
```

Se `XDG_DATA_HOME` estiver definido, ele substitui `~/.local/share`.
A descoberta automática prioriza um override explícito por ambiente, depois
`libexec`, depois esse diretório persistente e por último o PATH.

`innounp` é executado via Wine para ler o contêiner do setup. O disassembler é
Linux nativo. Nenhuma dessas etapas executa `setup.exe`. Consulte
[`THIRD_PARTY.md`](THIRD_PARTY.md) para fontes, versões e licenças.

As ferramentas não são incorporadas automaticamente ao `dist/fitgirl`;
redistribuição continua sujeita à revisão de licenças e fontes.
