# Experimento de inicialização encerrado

> Evidência histórica fora do escopo atual. Não usar como gate de instalação e
> não repetir na matriz de validação.

Testes limitados executam o jogo instalado via UMU e Proton-CachyOS-11, com
prefixo separado da árvore validada. O Wine privado do instalador não é usado
como runner. Sobreviver à janela de observação comprova somente inicialização do
processo; renderização, áudio, entrada e jogabilidade precisam de observação
visual.

O primeiro ensaio do Star Trucker com Proton-CachyOS-11 encerrou em 18,883
segundos por chamadas não implementadas em `win32u`/`shell32`. A repetição com
UMU-Proton-10.0-4 permaneceu ativa durante os 60 segundos completos. Assim, a
instalação iniciou com um runner e falhou com outro; o resultado não deve ser
atribuído ao MD5 ou ao extrator.

O executável Shipping do Directive 8020 chegou a abrir, mas o experimento foi
encerrado quando o escopo foi reafirmado: extração, estrutura e MD5/CRC. A
ferramenta de lançamento foi removida e jogabilidade não será testada.
