"""Language selection and terminal-message localization."""

from __future__ import annotations

import builtins
import os
import re
from typing import Any, Callable


LANGUAGE = "pt"
_ORIGINAL_PRINT = builtins.print
_ORIGINAL_INPUT = builtins.input

_TEXT = {
    "FITGIRL INSTALLER": "FITGIRL INSTALLER",
    "Conteúdo e opcionais:": "Content and optional files:",
    "  Digite s ou n.": "  Enter y or n.",
    "Digite s ou n.": "Enter y or n.",
    "Informe um caminho.": "Enter a path.",
    "Informe um número inteiro.": "Enter a whole number.",
    "CPUs permitidas para todo o trabalho": "CPUs available for all tasks",
    "Escolher outro caminho": "Choose another path",
    "Destino": "Destination",
    "Desempenho": "Performance",
    "Revisar e iniciar": "Review and start",
    "Origem:": "Source:",
    "Arquivos compactados:": "Compressed files:",
    "Espaço declarado pelo instalador:": "Installer-declared space:",
    "O setup e o jogo não serão executados.": "The setup and game will not be run.",
    "Jogo:": "Game:",
    "Destino:": "Destination:",
    "Conteúdo:": "Content:",
    "Dados selecionados:": "Selected data:",
    "Recursos:": "Resources:",
    "Validação:": "Verification:",
    "Espaço declarado pelo repack:": "Repack-declared space:",
    "somente arquivos principais": "main files only",
    "há volumes ausentes": "some volumes are missing",
    "Automático (recomendado)": "Automatic (recommended)",
    "Personalizado": "Custom",
    " — obrigatório": " — required",
    ": indisponível (arquivo ausente)": ": unavailable (file missing)",
    "A pasta de destino já existe; confira se é a instalação pretendida.":
        "The destination folder already exists; make sure it is the intended installation.",
    "Opção inválida.": "Invalid option.",
    "Plano de instalação validado.": "Installation plan validated.",
    "Componentes:": "Components:",
    "Etapas:": "Steps:",
    "Volumes:": "Volumes:",
    "Preparando arquivos temporários…": "Preparing temporary files…",
    "Preparando arquivos da instalação…": "Preparing installation files…",
    "Preparando ambiente para os codecs…": "Preparing the codec environment…",
    "Executando etapa auxiliar…": "Running helper step…",
    "Executando pós-processamento…": "Running post-processing…",
    "A instalação é retomável. O jogo não será configurado para iniciar.":
        "Installation can be resumed. The game will not be configured to launch.",
    "Instalação cancelada; nenhum arquivo foi alterado.":
        "Installation cancelled; no files were changed.",
    "Instalação concluída e arquivos verificados.": "Installation complete; files verified.",
    "Simulação concluída.": "Dry run complete.",
    "Conteúdo": "Content",
    "Inglês": "English",
    "Russo": "Russian",
    "Espanhol": "Spanish",
    "Alemão": "German",
    "Francês": "French",
    "Italiano": "Italian",
    "Japonês": "Japanese",
    "Arquivos principais": "Main files",
    "Redistribuíveis mantidos sem executar: ": "Redistributables preserved without running: ",
    "[MANIFESTOS] combinar base e addons presentes, preservando originais":
        "[MANIFESTS] Combining the base and available add-ons while preserving originals",
    "[AVISO] payload _Redist ausente; verificador original não foi preservado":
        "[WARNING] _Redist payload is missing; the original verifier was not preserved",
    "[AVISO] este setup não contém QuickSFV/manifestos para preservar":
        "[WARNING] This setup has no QuickSFV/manifests to preserve",
    "[AVISO] payload temporário divergiu do journal; será preservado e reconstruído":
        "[WARNING] Temporary payload differs from the journal; it will be preserved and rebuilt",
    "payload temporário divergiu após etapas concluídas; reconstrução automática recusada para preservar mutações e auxiliares":
        "Temporary payload differs after completed steps; automatic rebuild refused to preserve changes and helper files",
    "[AVISO] payload de aplicação divergiu do journal; será preservado":
        "[WARNING] Application payload differs from the journal; it will be preserved",
    "A instalação é retomável. O jogo não será configurado para iniciar.":
        "Installation can be resumed. The game will not be configured to launch.",
    "Instalação cancelada; nenhum arquivo foi alterado.": "Installation cancelled; no files were changed.",
    "CPUs aplica-se a todos os codecs; é diferente das threads BZip3.":
        "CPU affinity applies to all codecs; it is separate from BZip3 threads.",
    "MemoryHigh não pode exceder MemoryMax": "MemoryHigh cannot exceed MemoryMax",
    "Plano de instalação validado.": "Installation plan validated.",
    "Informe um número inteiro.": "Enter a whole number.",
    "Uso: fitgirl /caminho/do/repack": "Usage: fitgirl /path/to/repack",
    "\nO menu terminal solicitará destino, componentes e configurações.":
        "\nThe terminal menu will ask for the destination, components, and settings.",
    "Escolha os idiomas e opcionais. Enter mantém o padrão.":
        "Choose languages and optional files. Press Enter to keep the default.",
    "Caminho completo da pasta do jogo": "Full path to the game folder",
    "Caminho do repack": "Repack path",
    "Deseja limitar manualmente os recursos?": "Would you like to set resource limits manually?",
    "Usar o perfil de memória 2 GiB deste repack?": "Use this repack's 2 GiB memory profile?",
    "Memória do SREP em MiB": "SREP memory in MiB",
    "Threads do BZip3": "BZip3 threads",
    "Reduzir prioridade (nice, de 1 a 19)": "Lower process priority (nice, from 1 to 19)",
    "MemoryHigh em MiB (pressão suave)": "MemoryHigh in MiB (soft limit)",
    "MemoryMax em MiB (teto rígido; pode encerrar o codec)": "MemoryMax in MiB (hard limit; may terminate the codec)",
    "Iniciar ou retomar agora?": "Start or resume now?",
    "Conteúdo e opcionais:": "Content and optional files:",
    "Onde instalar? (fora do prefixo Wine)": "Where should the game be installed? (outside the Wine prefix)",
    "Destino (número ou caminho) [1]: ": "Destination (number or path) [1]: ",
    "Destino ou número da lista [1]: ": "Destination or list number [1]: ",
    "Plano": "Plan",
    "Etapa": "Step",
    "Confirmado": "Confirmed",
    "Já concluída": "Already complete",
    "PÓS-LEITURA": "POST-READ",
    "verificar requisitos deste Linux": "check the requirements of this Linux system",
    "identificar setup, opções e plano": "inspect the setup, options, and plan",
    "executar ou retomar o plano": "run or resume the plan",
    "perguntar componentes no terminal": "prompt for components in the terminal",
    "aplicar escritas INI condicionadas ao checkbox original use2gb": "apply INI changes guarded by the original use2gb checkbox",
    "threads para placeholders fgrplc do BZip3": "threads for BZip3 fgrplc placeholders",
    "limiar cgroup v2 suave em MiB": "soft cgroup v2 limit in MiB",
    "teto cgroup v2 rígido em MiB (pode causar OOM kill)": "hard cgroup v2 limit in MiB (may trigger an OOM kill)",
    "lista taskset, por exemplo 0-7 ou 0,2,4,6": "taskset CPU list, for example 0-7 or 0,2,4,6",
    "mostrar o journal": "show the journal",
    "pausar o grupo ativo": "pause the active process group",
    "retomar o grupo ativo": "resume the active process group",
    "metadados do Wine interno não suportados": "Unsupported internal Wine metadata",
    "este Wine interno requer Linux x86-64": "This internal Wine runtime requires Linux x86-64",
    "components inválido no manifesto": "Invalid components field in the plan",
    "payload de aplicação contém caminhos duplicados": "Application payload contains duplicate paths",
    "invocação FART não comprovada": "FART invocation has not been verified",
    "FART: padrão vazio": "FART: empty pattern",
    "combinação de manifestos não comprovada": "Manifest combination has not been verified",
    "não há etapa ativa registrada": "No active step is recorded",
    "--memory-high não pode exceder --memory-max": "--memory-high cannot exceed --memory-max",
    "Opção inválida. Digite 1 para português ou 2 para English.":
        "Invalid option. Enter 1 for Portuguese or 2 for English.",
    "innounp é PE, mas nenhum Wine foi encontrado para a análise":
        "innounp is a PE executable, but Wine was not found for analysis",
    "ISExec contém aspas internas em expanded_quoted": "ISExec contains nested quotes in expanded_quoted",
    "FART: codificação não comprovada": "FART: encoding has not been verified",
    "o grupo de processos registrado não existe mais": "The recorded process group no longer exists",
    "nome inválido nos metadados do runtime": "Invalid name in runtime metadata",
    "SHA-256 inválido nos metadados do runtime": "Invalid SHA-256 in runtime metadata",
    "arquivo do Wine interno ausente ou com SHA-256 inválido": "Internal Wine archive is missing or has an invalid SHA-256",
    "caminho inesperado no arquivo do Wine": "Unexpected path in the Wine archive",
    "Wine extraído não corresponde ao executável validado": "Extracted Wine does not match the verified executable",
    "Requisitos incompatíveis:": "Incompatible requirements:",
    "o projeto requer Linux": "the project requires Linux",
    "o runtime atual requer arquitetura x86-64": "the current runtime requires x86-64 architecture",
    "é necessária glibc 2.38 ou superior": "glibc 2.38 or newer is required",
    "é necessário Python 3.12 ou superior": "Python 3.12 or newer is required",
}

_MONITOR_PATTERN_NAMES = {
    r"ATIVO", r"SEM AVANCO", r"RELEITURA INTERNA",
    r"CPU OCUPADA; progresso não comprovado", r"ORIGEM INDISPONÍVEL",
    r"PÓS-LEITURA", r"LEITURA", r"leitura", r"sem avanço (\d+)s",
    r"ativo", r"CPU ocupada", r"CPU sem avanço", r"releitura",
    r"(\d+) arq\b", r"fase=([\w-]+)", r"entrada=",
    r"pico-rss=", r"pico-pss=",
}

_PATTERNS: tuple[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]], ...] = (
    (re.compile(r"Etapa (\d+) de 4  \|  (.*)"), lambda m: f"Step {m.group(1)} of 4  |  {translate(m.group(2))}"),
    (re.compile(r"^Origem: (.*)$"), r"Source: \1"),
    (re.compile(r"^Arquivos compactados: (.*)$"), r"Compressed files: \1"),
    (re.compile(r"^Espaço declarado pelo instalador: (.*)$"), r"Installer-declared space: \1"),
    (re.compile(r"^  (\d+\. )Escolher outro caminho$"), r"  \1Choose another path"),
    (re.compile(r"^  (.*) — obrigatório$"), r"  \1 — required"),
    (re.compile(r"^  (.*): indisponível \(arquivo ausente\)$"), r"  \1: unavailable (file missing)"),
    (re.compile(r"^(.+) \[(S/n|s/N)\] $"), lambda m: f"{translate(m.group(1))} [{'Y/n' if m.group(2) == 'S/n' else 'y/N'}] "),
    (re.compile(r"^(.+?)( \[.*?\])?: $"), lambda m: f"{translate(m.group(1))}{translate(m.group(2) or '')}: "),
    (re.compile(r"  Incluir (.*)\? \[(S/n|s/N)\] "), lambda m: f"  Include {translate(m.group(1))}? [{'Y/n' if m.group(2) == 'S/n' else 'y/N'}] "),
    (re.compile(r"Destino \(número ou caminho\) \[1\]: "), "Destination (number or path) [1]: "),
    (re.compile(r"\nOnde instalar\? \(fora do prefixo Wine\)"), "\nWhere should the game be installed? (outside the Wine prefix)"),
    (re.compile(r"Destino indisponível: (.*)"), r"Destination unavailable: \1"),
    (re.compile(r"[Dd]isponível: (\d+) CPUs · até (\d+) MiB de memória para o instalador\."),
     r"Available: \1 CPUs · up to \2 MiB of memory for the installer."),
    (re.compile(r"Etapa (\d+)/(\d+) já validada; retomando\."), r"Step \1/\2 already validated; resuming."),
    (re.compile(r"Etapa concluída · (.*) geral"), r"Step complete · \1 overall"),
    (re.compile(r"Etapa (\d+)/(\d+): (.*)"), r"Step \1/\2: \3"),
    (re.compile(r"Plano:\s+não reconhecido \((.*)\)"), r"Plan:       not recognized (\1)"),
    (re.compile(r"Jogo:\s+(.*)"), r"Game:       \1"),
    (re.compile(r"Etapa (\d+) de 4  \|  (.*)"), r"Step \1 of 4  |  \2"),
    (re.compile(r"Digite s ou n\.?"), "Enter y or n."),
    (re.compile(r"Valor inválido: (.*)\. Use, por exemplo, (.*)\."), r"Invalid value: \1. Use a format such as \2."),
    (re.compile(r"Use um valor entre (.*) e (.*)\."), r"Enter a value between \1 and \2."),
    (re.compile(r"O mínimo é (.*)\."), r"The minimum is \1."),
    (re.compile(r"[\[]AVISO[\]] (.*)"), r"[WARNING] \1"),
    (re.compile(r"[\[]ERRO[\]] (.*)"), r"[ERROR] \1"),
    (re.compile(r"[\[]INFO[\]] (.*)"), r"[INFO] \1"),
    (re.compile(r"[\[]OK[\]] (.*)"), r"[OK] \1"),
    (re.compile(r"[\[]PULA[\]] (.*)"), r"[SKIP] \1"),
    (re.compile(r"não foi possível ler (.*?): (.*)"), r"Could not read \1: \2"),
    (re.compile(r"objeto JSON esperado em (.*)"), r"Expected a JSON object in \1"),
    (re.compile(r"\[AVISO\] journal inválido preservado em (.*); backup restaurado"),
     r"[WARNING] Invalid journal preserved at \1; restored the backup"),
    (re.compile(r"esperado um setup\.exe em (.*); encontrados: (\d+)"),
     r"Expected one setup.exe in \1; found: \2"),
    (re.compile(r"nenhum manifesto inequívoco corresponde ao setup\.exe; use --manifest após analisar o CompiledCode\.bin"),
     "No unambiguous plan matches setup.exe; use --manifest after analyzing CompiledCode.bin"),
    (re.compile(r"manifesto (.*) não aceita este setup\.exe \((.*)\); recusei executar um plano possivelmente incompatível"),
     r"Plan \1 does not accept this setup.exe (\2); refusing to run a potentially incompatible plan"),
    (re.compile(r"manifesto (.*) bloqueado por efeito externo não representado no plano: (.*)"),
     r"Plan \1 is blocked by an external effect not represented in the plan: \2"),
    (re.compile(r"manifesto (.*) ainda é rascunho; revise condições/ações e remova draft/review_required antes de instalar"),
     r"Plan \1 is still a draft; review its conditions/actions and clear draft/review_required before installing"),
    (re.compile(r"caminho do manifesto escapa da raiz permitida: (.*)"), r"Plan path escapes its allowed root: \1"),
    (re.compile(r"componentes desconhecidos: (.*)"), r"Unknown components: \1"),
    (re.compile(r"o componente obrigatório (.*) não pode ser desativado"), r"Required component \1 cannot be disabled"),
    (re.compile(r"componente (.*) desativado: (.*) não está presente"), r"Component \1 disabled: \2 is missing"),
    (re.compile(r"Valor inválido: (.*)\. Use, por exemplo, (.*)\."), r"Invalid value: \1. For example, use \2."),
    (re.compile(r"override de desenvolvimento FITGIRL_WINE_BIN inválido: (.*)"), r"Invalid FITGIRL_WINE_BIN development override: \1"),
    (re.compile(r"nenhum Wine/Proton utilizável foi encontrado\. Instale Wine/Proton compatível ou configure FITGIRL_WINE_BIN para um executável existente"),
     "No usable Wine/Proton was found. Install a compatible version or set FITGIRL_WINE_BIN to an existing executable"),
    (re.compile(r"Destino indisponível: (.*)"), r"Destination unavailable: \1"),
    (re.compile(r"não é possível criar a pasta neste disco; escolha outro destino gravável"),
     "Cannot create the folder on this drive; choose another writable destination"),
    (re.compile(r"nome do jogo inválido para compor o destino"), "Invalid game name for the destination path"),
    (re.compile(r"diretório do repack não existe: (.*)"), r"Repack directory does not exist: \1"),
    (re.compile(r"CPUs aplica-se a todos os codecs; é diferente das threads BZip3\."),
     "CPU affinity applies to all codecs; it is separate from BZip3 threads."),
    (re.compile(r"MemoryHigh não pode exceder MemoryMax"), "MemoryHigh cannot exceed MemoryMax"),
    (re.compile(r"payload temporário contém nomes duplicados sem distinção de caixa"),
     "Temporary payload contains case-insensitive duplicate names"),
    (re.compile(r"innoextract indisponível para materializar payload: (.*)"), r"innoextract is unavailable to prepare the payload: \1"),
    (re.compile(r"innoextract encerrou com código (\d+); veja (.*) e (.*)"), r"innoextract exited with code \1; see \2 and \3"),
    (re.compile(r"etapa encerrou com código (\d+)"), r"Step exited with code \1"),
    (re.compile(r"arquivo intermediário ausente: (.*)"), r"Intermediate file is missing: \1"),
    (re.compile(r"volume ausente: (.*)"), r"Volume is missing: \1"),
    (re.compile(r"MD5 inválido em (.*): esperado (.*), obtido (.*)"), r"Invalid MD5 for \1: expected \2, got \3"),
    (re.compile(r"script (.*) encerrou com código (\d+)"), r"Script \1 exited with code \2"),
    (re.compile(r"pós-processamento ausente: (.*)"), r"Post-processing file is missing: \1"),
    (re.compile(r"transação anterior não resolvida: (.*)"), r"Previous transaction is unresolved: \1"),
    (re.compile(r"rollback recusou caminho não confinado: (.*)"), r"Rollback refused an unconfined path: \1"),
    (re.compile(r"\[ROLLBACK\] (.*) restaurado"), r"[ROLLBACK] \1 restored"),
    (re.compile(r"[\[]FALHOU[\]] (.*): esperado=(.*) obtido=(.*)"), r"[FAILED] \1: expected=\2 got=\3"),
    (re.compile(r"[\[]FALHOU[\]] (.*)"), r"[FAILED] \1"),
    (re.compile(r"\[VERIFICADOR\] mantendo manifesto combinado validado: (.*)"), r"[VERIFIER] Keeping validated combined manifest: \1"),
    (re.compile(r"\[VERIFICADOR\] mantendo QuickSFV x64 compatível: (.*)"), r"[VERIFIER] Keeping compatible QuickSFV x64: \1"),
    (re.compile(r"\[AVISO\] payload _Redist ausente; verificador original não foi preservado"),
     "[WARNING] _Redist payload is missing; the original verifier was not preserved"),
    (re.compile(r"\[AVISO\] este setup não contém QuickSFV/manifestos para preservar"),
     "[WARNING] This setup has no QuickSFV/manifests to preserve"),
    (re.compile(r"etapa anterior ainda está ativa no grupo (\d+); não iniciarei uma cópia concorrente"),
     r"Previous step is still active in process group \1; refusing to start a concurrent copy"),
    (re.compile(r"tipo de etapa não suportado: (.*)"), r"Unsupported step type: \1"),
    (re.compile(r"--srep-memory deve ficar entre (.*) MiB nesta máquina"), r"--srep-memory must be between \1 MiB on this machine"),
    (re.compile(r"--bzip3-threads deve ficar entre (.*)"), r"--bzip3-threads must be between \1"),
    (re.compile(r"--memory-high deve ficar entre (.*) MiB nesta máquina"), r"--memory-high must be between \1 MiB on this machine"),
    (re.compile(r"--memory-max deve ficar entre (.*) MiB nesta máquina"), r"--memory-max must be between \1 MiB on this machine"),
    (re.compile(r"--cpus inválido: (.*)"), r"Invalid --cpus value: \1"),
    (re.compile(r"ISExec (.*) sem expressão de parâmetros comprovada"), r"ISExec \1 has no verified parameter expression"),
    (re.compile(r"CPUs permitidas para todo o trabalho \[(.*) = todas\]"), r"CPUs allowed for all tasks [\1 = all]"),
    (re.compile(r"Memória do SREP em MiB \(somente esse descompressor\)"), "SREP memory in MiB (this decompressor only)"),
    (re.compile(r"Threads BZip3 \(somente esse codec\)"), "BZip3 threads (this codec only)"),
    (re.compile(r"MemoryHigh em MiB \(limite suave\)"), "MemoryHigh in MiB (soft limit)"),
    (re.compile(r"MemoryMax em MiB \(limite rígido; pode reiniciar uma etapa\)"), "MemoryMax in MiB (hard limit; may restart a step)"),
    (re.compile(r"Escolha onde instalar\. A pasta será criada após a confirmação\."), "Choose where to install. The folder will be created after confirmation."),
    (re.compile(r"Escolha a pasta de destino\. Ela será criada após a confirmação\."), "Choose the destination folder. It will be created after confirmation."),
    (re.compile(r"  (\d+)\. (.*) \(([\d.]+) GiB livres\) · (.*)"), r"  \1. \2 (\3 GiB free) · \4"),
    (re.compile(r"\( ([\d.]+) GiB livres\)"), r"(\1 GiB free)"),
    (re.compile(r"sem permissão"), "no write access"),
    (re.compile(r"leitura"), "reading"),
    (re.compile(r"sem avanço (\d+)s"), r"no progress \1s"),
    (re.compile(r"ativo"), "active"),
    (re.compile(r"CPU ocupada"), "CPU busy"),
    (re.compile(r"CPU sem avanço"), "CPU with no progress"),
    (re.compile(r"releitura"), "rereading"),
    (re.compile(r"(\d+) arq\b"), r"\1 files"),
    (re.compile(r"fase=([\w-]+)"), r"phase=\1"),
    (re.compile(r"entrada="), "input="),
    (re.compile(r"pico-rss="), "peak-rss="),
    (re.compile(r"pico-pss="), "peak-pss="),
    (re.compile(r"[\[]OK[\]] payload temporário: (\d+) arquivos já validados"), r"[OK] Temporary payload: \1 files already validated"),
    (re.compile(r"[\[]OK[\]] payload de aplicação: (\d+) arquivos já validados"), r"[OK] Application payload: \1 files already validated"),
    (re.compile(r"[\[]OK[\]] payload legado de aplicação adotado e validado: (\d+) arquivos"), r"[OK] Legacy application payload adopted and validated: \1 files"),
    (re.compile(r"\[PAYLOAD-APP\] árvore anterior preservada em (.*)"), r"[PAYLOAD-APP] Previous tree preserved at \1"),
    (re.compile(r"\[PAYLOAD-APP\] (\d+) arquivos publicados e validados"), r"[PAYLOAD-APP] Published and validated \1 files"),
    (re.compile(r"\[PREFIXO\] inicializando (.*)"), r"[PREFIX] Initializing \1"),
    (re.compile(r"dosdevice W: inesperadamente é diretório: (.*)"), r"dosdevice W: is unexpectedly a directory: \1"),
    (re.compile(r"arquivo intermediário ausente: (.*)"), r"Intermediate file is missing: \1"),
    (re.compile(r"volume ausente: (.*)"), r"Volume is missing: \1"),
    (re.compile(r"pós-processamento ausente: (.*)"), r"Post-processing file is missing: \1"),
    (re.compile(r"executável de pós-processamento ausente: (.*)"), r"Post-processing executable is missing: \1"),
    (re.compile(r"delete_after aceita somente arquivos: (.*)"), r"delete_after only accepts files: \1"),
    (re.compile(r"transação (.*) sem raiz de backup"), r"Transaction \1 has no backup root"),
    (re.compile(r"raiz de transação fora do scratch: (.*)"), r"Transaction root is outside scratch: \1"),
    (re.compile(r"backup de transação fora da quarentena: (.*)"), r"Transaction backup is outside quarantine: \1"),
    (re.compile(r"FART: arquivo não regular: (.*)"), r"FART: not a regular file: \1"),
    (re.compile(r"FART: arquivo binário inesperado: (.*)"), r"FART: unexpected binary file: \1"),
    (re.compile(r"FART: pós-condição divergente: (.*)"), r"FART: postcondition mismatch: \1"),
    (re.compile(r"cmd del: escopo de rollback não comprovado"), "cmd del: rollback scope not proven"),
    (re.compile(r"tipo inesperado para remoção: (.*)"), r"Unexpected type for removal: \1"),
    (re.compile(r"origem e quarentena coexistem: (.*)"), r"Source and quarantine both exist: \1"),
    (re.compile(r"arquivo de pós-processamento ausente: (.*)"), r"Post-processing file is missing: \1"),
    (re.compile(r"manifesto base ausente: (.*)"), r"Base manifest is missing: \1"),
    (re.compile(r"addon incompleto: (.*)"), r"Incomplete add-on: \1"),
    (re.compile(r"hashes conflitantes nos manifestos: (.*)"), r"Conflicting hashes in manifests: \1"),
    (re.compile(r"QuickSFV x64 externo ausente: (.*)"), r"External QuickSFV x64 is missing: \1"),
    (re.compile(r"QuickSFV x64 externo não é PE32\+ x86-64: (.*)"), r"External QuickSFV x64 is not PE32+ x86-64: \1"),
    (re.compile(r"manifesto de integridade ausente: (.*)"), r"Integrity manifest is missing: \1"),
    (re.compile(r"manifesto de integridade ausente: (.*)"), r"Integrity manifest is missing: \1"),
    (re.compile(r"manifesto base ausente: (.*)"), r"Base manifest is missing: \1"),
    (re.compile(r"plano automático salvo em (.*), mas bloqueado por efeito externo: (.*)"), r"Automatic plan saved to \1 but blocked by an external effect: \2"),
    (re.compile(r"plano automático gerado em (.*), com (\d+) etapas; instalação recusada porque condições e ações ainda não foram comprovadas"), r"Automatic plan generated at \1 with \2 steps; installation refused because its conditions and actions are not yet proven"),
    (re.compile(r"\[INFO\] plano automático aceito: (\d+) etapas provadas contra uma ISDone\.dll já analisada; o MD5 do repack confere o resultado"), r"[INFO] Automatic plan accepted: \1 steps proven against an already analysed ISDone.dll; the repack's MD5 manifest checks the result"),
    (re.compile(r"a etapa anterior ainda está ativa no grupo (\d+); não iniciarei uma cópia concorrente"), r"The previous step is still active in process group \1; refusing to start a concurrent copy"),
    (re.compile(r"nenhum arquivo foi alterado"), "no files were changed"),
    (re.compile(r"[\[]GLOBAL[\]] (.*) confirmado"), r"[GLOBAL] \1 confirmed"),
    (re.compile(r"[\[]GLOBAL[\]] (.*) simulado"), r"[GLOBAL] \1 simulated"),
    (re.compile(r"Instalação concluída e arquivos verificados\."), "Installation complete; files verified."),
    (re.compile(r"Simulação concluída\."), "Dry run complete."),
    (re.compile(r"ATIVO"), "ACTIVE"),
    (re.compile(r"SEM AVANCO"), "NO PROGRESS"),
    (re.compile(r"RELEITURA INTERNA"), "INTERNAL READ"),
    (re.compile(r"CPU OCUPADA; progresso não comprovado"), "CPU BUSY; progress unconfirmed"),
    (re.compile(r"ORIGEM INDISPONÍVEL"), "SOURCE UNAVAILABLE"),
    (re.compile(r"PÓS-LEITURA"), "POST-READ"),
    (re.compile(r"LEITURA"), "READING"),
)


def translate(value: str) -> str:
    if LANGUAGE != "en":
        return value
    if value in _TEXT:
        return _TEXT[value]
    if value.startswith("Ambiente detectado:"):
        for source, translated in (
            ("Ambiente detectado:", "Detected environment:"),
            ("arquitetura", "architecture"),
            ("desconhecida", "unknown"),
            ("Requisitos incompatíveis:", "Incompatible requirements:"),
            ("Consulte docs/ARCHITECTURE.md para os requisitos completos.", "See docs/ARCHITECTURE.md for the complete requirements."),
            ("biblioteca de sistema ausente:", "missing system library:"),
            ("comando de sistema ausente:", "missing system command:"),
            ("comando de sistema", "system command"),
            ("o runtime atual requer arquitetura x86-64", "the current runtime requires x86-64 architecture"),
            ("Wine/Proton ausente; instale-o ou configure FITGIRL_WINE_BIN", "Wine/Proton is missing; install it or set FITGIRL_WINE_BIN"),
            ("Python precisa oferecer tarfile.data_filter para extração segura", "Python must provide tarfile.data_filter for safe extraction"),
            ("é necessária glibc 2.38 ou superior", "glibc 2.38 or newer is required"),
            ("é necessário Python 3.12 ou superior", "Python 3.12 or newer is required"),
        ):
            value = value.replace(source, translated)
        return value
    is_monitor_line = value.startswith("[MONITOR]")
    for pattern, replacement in sorted(_PATTERNS, key=lambda item: len(item[0].pattern), reverse=True):
        if pattern.pattern in _MONITOR_PATTERN_NAMES and not is_monitor_line:
            continue
        if pattern.search(value):
            return pattern.sub(replacement, value)
    return value


def _localized_print(*values: Any, **kwargs: Any) -> None:
    _ORIGINAL_PRINT(*(translate(value) if isinstance(value, str) else value for value in values), **kwargs)


def _localized_input(prompt: str = "") -> str:
    return _ORIGINAL_INPUT(translate(prompt))


def activate(language: str) -> tuple[Any, Any, str | None, str]:
    global LANGUAGE
    previous = (builtins.print, builtins.input, os.environ.get("FITGIRL_LANGUAGE"), LANGUAGE)
    LANGUAGE = "en" if language == "en" else "pt"
    os.environ["FITGIRL_LANGUAGE"] = LANGUAGE
    builtins.print = _localized_print
    builtins.input = _localized_input
    return previous


def restore(previous: tuple[Any, Any, str | None, str]) -> None:
    global LANGUAGE
    builtins.print, builtins.input, old_language, LANGUAGE = previous
    if old_language is None:
        os.environ.pop("FITGIRL_LANGUAGE", None)
    else:
        os.environ["FITGIRL_LANGUAGE"] = old_language
