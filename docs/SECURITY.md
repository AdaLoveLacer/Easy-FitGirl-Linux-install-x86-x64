# Segurança

O extrator evita executar a GUI e o script Inno, mas ainda carrega e executa
código Windows retirado do repack:

- `unarc.dll` é carregado pelo helper PE32;
- filtros e workers definidos em `arc.ini` podem ser iniciados pelo FreeArc;
- etapas de pós-processamento declaradas no manifesto podem executar scripts
  extraídos do setup (por exemplo, `mover.bat`);
- Wine não é uma sandbox de segurança.

Portanto, use somente volumes cuja procedência e hashes tenham sido verificados.
Para analisar material não confiável, use uma conta sem privilégios, prefixo
Wine descartável, mounts somente leitura para a origem e isolamento adicional
por container/VM. Nunca execute a ferramenta como root.

Logs podem conter caminhos locais. Revise-os antes de anexá-los a issues.

