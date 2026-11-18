<#
.SYNOPSIS
  Instala (ou atualiza) o Real Task Scheduler no Windows, sem Docker.

.DESCRIPTION
  - Com Python 3.12+ na máquina: cria um ambiente virtual e instala o pacote (wheel).
  - Sem Python: usa o executável autônomo (não precisa de nada instalado).
  Por padrão escolhe sozinho (-Mode auto). Registra o RTS no Agendador de Tarefas para
  iniciar junto com o Windows (requer PowerShell como Administrador; use -NoService para pular).

  Reexecutar o script atualiza a instalação e preserva configuração (.env) e dados.

.EXAMPLE
  irm https://raw.githubusercontent.com/gabriel0torres/real-task-manager/main/install.ps1 | iex

.EXAMPLE
  .\install.ps1 -Mode standalone -Port 8080
  .\install.ps1 -From .\rts-0.1.0-py3-none-any.whl -NoService
#>
[CmdletBinding()]
param(
    [ValidateSet("auto", "python", "standalone")] [string] $Mode = "auto",
    [string] $Version = "latest",
    [string] $From = "",
    [string] $InstallDir = "",
    [ValidateRange(1, 65535)] [int] $Port = 8000,
    [string] $AdminPassword = "",
    [switch] $NoService,
    [string] $Repo = "gabriel0torres/real-task-manager"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Info($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# When run by the web updater (update.ps1), report steps to its progress log.
function Report-Progress([string] $step, [string] $status, [string] $detail = "") {
    if (-not $env:RTS_UPDATE_PROGRESS) { return }
    $event = [ordered]@{ step = $step; status = $status; at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'") }
    if ($detail) { $event.detail = $detail }
    try {
        [IO.File]::AppendAllText($env:RTS_UPDATE_PROGRESS, (($event | ConvertTo-Json -Compress) + "`n"), (New-Object Text.UTF8Encoding $false))
    } catch { }
}
function Warn($msg) { Write-Host "AVISO: $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "ERRO: $msg" -ForegroundColor Red; exit 1 }

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $InstallDir) {
    $InstallDir = if ($IsAdmin) { Join-Path $env:ProgramData "RTS" } else { Join-Path $env:LOCALAPPDATA "RTS" }
}
$Arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { Fail "Somente Windows 64 bits é suportado." }

# ------------------------------------------------------------------ python
function Test-Python([string] $exe, [string[]] $pyArgs) {
    # Run the candidate: the Microsoft Store placeholder ("python" with no Python installed)
    # just prints a message and fails, while real installs (including the Python Install
    # Manager aliases in WindowsApps) answer the version check.
    $ErrorActionPreference = "Continue"
    try {
        $ok = & $exe @($pyArgs + @("-c", "import sys, venv; print(sys.version_info >= (3, 12))")) 2>$null
        return "$ok".Trim() -eq "True"
    } catch { return $false } finally { $ErrorActionPreference = "Stop" }
}

function Find-Python {
    # 1. Commands on the PATH.
    foreach ($c in @(@{ exe = "py"; args = @("-3") }, @{ exe = "python"; args = @() }, @{ exe = "python3"; args = @() })) {
        $cmd = Get-Command $c.exe -ErrorAction SilentlyContinue
        if ($cmd -and (Test-Python $cmd.Source $c.args)) { return @{ exe = $cmd.Source; args = $c.args } }
    }
    # 2. Installations the PATH doesn't show. The web updater runs as SYSTEM, whose PATH
    #    usually lacks a Python installed by a user: look at the registry (PEP 514), the
    #    Python of the existing virtual environment and the usual folders.
    $paths = @()
    foreach ($root in "HKLM:\SOFTWARE\Python\PythonCore", "HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore", "HKCU:\SOFTWARE\Python\PythonCore") {
        foreach ($key in (Get-ChildItem $root -ErrorAction SilentlyContinue)) {
            $install = Get-ItemProperty (Join-Path $key.PSPath "InstallPath") -ErrorAction SilentlyContinue
            if ($install.ExecutablePath) { $paths += $install.ExecutablePath }
            elseif ($install."(default)") { $paths += Join-Path $install."(default)" "python.exe" }
        }
    }
    $cfg = Join-Path $InstallDir "venv\pyvenv.cfg"
    if (Test-Path $cfg) {
        $homeLine = (Get-Content $cfg) -match "^home\s*=" | Select-Object -First 1
        if ($homeLine) { $paths += Join-Path (($homeLine -split "=", 2)[1].Trim()) "python.exe" }
    }
    $paths += @(Get-ChildItem "$env:ProgramFiles\Python3*\python.exe", "$env:SystemDrive\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object { $_.FullName })
    foreach ($path in ($paths | Select-Object -Unique)) {
        if ((Test-Path $path) -and (Test-Python $path @())) { return @{ exe = $path; args = @() } }
    }
    return $null
}

# On an update the existing virtual environment already has its own Python.
$VenvPython = Join-Path $InstallDir "venv\Scripts\python.exe"
$HasVenv = (Test-Path $VenvPython) -and (Test-Python $VenvPython @())
$Python = Find-Python
if ($From) {
    if (-not (Test-Path $From)) { Fail "Arquivo não encontrado: $From" }
    $From = (Resolve-Path $From).Path
    if ($Mode -eq "auto") { $Mode = if ($From -like "*.whl") { "python" } else { "standalone" } }
}
if ($Mode -eq "auto") { $Mode = if ($Python -or $HasVenv) { "python" } else { "standalone" } }
if ($Mode -eq "python" -and -not $Python -and -not $HasVenv) {
    Fail "Python 3.12+ não encontrado. Instale-o (para todos os usuários) ou use -Mode standalone."
}
Info "Modo de instalação: $Mode  |  diretório: $InstallDir"

# ------------------------------------------------------------------ download
# Release files are downloaded straight from github.com/<repo>/releases/download: their
# names are predictable, and the GitHub API (60 requests per hour per IP without login)
# is not needed.
function Resolve-Tag {
    if ($Version -ne "latest") { return $(if ($Version.StartsWith("v")) { $Version } else { "v$Version" }) }
    Info "Consultando a versão mais nova em github.com/$Repo ..."
    try {
        $response = (Invoke-WebRequest "https://github.com/$Repo/releases/latest" -Method Head -UseBasicParsing).BaseResponse
        $final = if ($response.ResponseUri) { $response.ResponseUri } else { $response.RequestMessage.RequestUri }
    } catch { Fail "Não foi possível consultar github.com/$Repo ($_)" }
    if ("$final" -notmatch "/releases/tag/([^/?#]+)") { Fail "Nenhuma Release publicada em $Repo." }
    return $Matches[1]
}

function Get-Artifact([string] $pattern) {
    if ($From) { return $From }
    $tag = Resolve-Tag
    $name = $pattern.Replace("*", $tag.TrimStart("v"))
    $target = Join-Path $env:TEMP $name
    Info "Baixando $name ($tag)..."
    try { Invoke-WebRequest "https://github.com/$Repo/releases/download/$tag/$name" -OutFile $target -UseBasicParsing }
    catch { Fail "Não foi possível baixar $name da versão $tag (a versão existe?): $_" }
    return $target
}

# ------------------------------------------------------------------ stop running instance
$Tasks = @("RTS API", "RTS Worker")
if ($IsAdmin -and -not $NoService) {
    foreach ($t in $Tasks) {
        if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
            Info "Parando a tarefa agendada '$t' para atualizar..."
            Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 2
}

# ------------------------------------------------------------------ port
$EnvFile = Join-Path $InstallDir ".env"
$FreshInstall = -not (Test-Path $EnvFile)

function Set-EnvValue([string] $key, [string] $value) {
    # Replace (or append) "KEY=value" in .env, keeping everything else as is.
    $lines = @(Get-Content -Path $EnvFile -Encoding UTF8 | Where-Object { $_ -notmatch "^$key=" })
    if ($value) { $lines += "$key=$value" }
    [IO.File]::WriteAllText($EnvFile, (($lines -join "`r`n") + "`r`n"), (New-Object Text.UTF8Encoding $false))
}

function Get-EnvValue([string] $key) {
    if (-not (Test-Path $EnvFile)) { return "" }
    $line = Get-Content -Path $EnvFile -Encoding UTF8 | Where-Object { $_ -match "^$key=" } | Select-Object -Last 1
    if ($line) { return ($line -replace "^$key=", "").Trim() }
    return ""
}

function Test-PortInUse([int] $p) {
    # Any listener (IPv4 or IPv6, any address) conflicts with the API, which binds 0.0.0.0.
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        if (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) { return $true }
    }
    # Also catches ports reserved by Windows (Hyper-V/WSL "excluded port ranges"), which have
    # no listener but cannot be bound. Loopback only, so the firewall never prompts.
    $listener = New-Object Net.Sockets.TcpListener ([Net.IPAddress]::Loopback, $p)
    try { $listener.Start(); return $false } catch { return $true } finally { try { $listener.Stop() } catch { } }
}

function Get-PortOwner([int] $p) {
    if (-not (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)) { return "outro programa" }
    $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) { return "$($proc.ProcessName) (PID $($conn.OwningProcess))" }
        return "PID $($conn.OwningProcess)"
    }
    return "reservada pelo Windows"
}

function Test-RtsOnPort([int] $p) {
    try {
        $h = Invoke-RestMethod "http://127.0.0.1:$p/api/v1/health" -TimeoutSec 3
        return ($h.status -eq "ok" -and $h.version)
    } catch { return $false }
}

function Find-FreePort([int] $start) {
    for ($p = $start + 1; $p -le [Math]::Min($start + 100, 65535); $p++) {
        if (-not (Test-PortInUse $p)) { return $p }
    }
    return 0
}

# Port the installation will use: -Port on a fresh install (or when passed explicitly),
# otherwise the one already in .env.
$PortExplicit = $PSBoundParameters.ContainsKey("Port")
$CurrentPort = 0
if (-not $FreshInstall) {
    [void] [int]::TryParse((Get-EnvValue "RTS_PORT"), [ref] $CurrentPort)
    if (-not $CurrentPort) { $CurrentPort = 8000 }
}
$WantedPort = if ($FreshInstall -or $PortExplicit) { $Port } else { $CurrentPort }
$EffectivePort = $WantedPort

$busy = Test-PortInUse $WantedPort
if ($busy -and -not $FreshInstall -and $WantedPort -eq $CurrentPort) {
    # Upgrade: the RTS stopped above may take a moment to release the port...
    for ($i = 0; $busy -and $i -lt 5; $i++) { Start-Sleep 1; $busy = Test-PortInUse $WantedPort }
    # ...or it is this same installation still running (started by hand, or a scheduled task
    # this non-admin session cannot stop). Windows locks the files of a running program, so
    # the upgrade would fail halfway: stop here instead.
    if ($busy -and (Test-RtsOnPort $WantedPort)) {
        Fail ("O RTS desta instalação está em execução na porta $WantedPort ($(Get-PortOwner $WantedPort)). " +
              "Feche-o (ou, como Administrador: Stop-ScheduledTask 'RTS API','RTS Worker') e rode o instalador de novo.")
    }
}
if ($busy) {
    $owner = Get-PortOwner $WantedPort
    $free = Find-FreePort $WantedPort
    if ($PortExplicit) {
        $hint = if ($free) { " Escolha outra, por exemplo: -Port $free" } else { " Escolha outra com -Port." }
        Fail "A porta $WantedPort já está em uso ($owner).$hint"
    }
    if (-not $free) { Fail "A porta $WantedPort e as 100 seguintes estão em uso. Escolha uma livre com -Port." }
    Warn "A porta $WantedPort já está em uso ($owner); o RTS usará a porta $free."
    $EffectivePort = $free
}
Info "Porta da interface web: $EffectivePort"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# ------------------------------------------------------------------ install
if ($Mode -eq "python") {
    $wheel = Get-Artifact "rts-*-py3-none-any.whl"
    $venv = Join-Path $InstallDir "venv"
    if ($HasVenv) {
        Info "Usando o ambiente virtual existente ($venv)."
    } else {
        if (-not $Python) { Fail "Python 3.12+ não encontrado para recriar o ambiente virtual." }
        if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }  # broken: its Python is gone
        Info "Criando ambiente virtual com $($Python.exe)..."
        & $Python.exe @($Python.args + @("-m", "venv", $venv))
        if ($LASTEXITCODE) { Fail "Falha ao criar o ambiente virtual." }
    }
    $vpy = Join-Path $venv "Scripts\python.exe"
    Info "Instalando o pacote (pode levar alguns minutos)..."
    Report-Progress "install" "running" "instalando o pacote Python e as dependências"
    $pipHint = " Se o RTS estiver em execução (por exemplo com 'rts.cmd start'), feche-o e rode o instalador de novo."
    & $vpy -m pip install --upgrade --quiet --disable-pip-version-check pip
    & $vpy -m pip install --upgrade --force-reinstall --no-deps --quiet --disable-pip-version-check "$wheel"
    if ($LASTEXITCODE) { Fail "Falha na instalação do pacote.$pipHint" }
    & $vpy -m pip install --quiet --disable-pip-version-check "$wheel[postgres]"
    if ($LASTEXITCODE) { Fail "Falha na instalação das dependências.$pipHint" }
    $Runner = Join-Path $venv "Scripts\rts.exe"
    $other = Join-Path $InstallDir "app"
    if (Test-Path $other) { Remove-Item -Recurse -Force $other }
} else {
    $zip = Get-Artifact "rts-*-windows-$Arch.zip"
    $app = Join-Path $InstallDir "app"
    if (Test-Path $app) {
        try { Remove-Item -Recurse -Force $app }
        catch { Fail "Não foi possível substituir $app (o RTS está em execução?). Feche-o e rode o instalador de novo. ($_)" }
    }
    Info "Extraindo o executável..."
    Report-Progress "install" "running" "extraindo o executável"
    Expand-Archive -Path $zip -DestinationPath $app -Force
    $Runner = Join-Path $app "rts\rts.exe"
}
if (-not (Test-Path $Runner)) { Fail "Executável não encontrado após a instalação: $Runner" }

# ------------------------------------------------------------------ configuration
$GeneratedPassword = $null
if ($FreshInstall) {
    $dataDir = Join-Path $InstallDir "data"
    $content = @"
# Configuração do Real Task Scheduler (veja o README para todas as opções)
RTS_DATA_DIR=$dataDir
RTS_PORT=$EffectivePort
RTS_ADMIN_USERNAME=admin
RTS_DEFAULT_TIMEZONE=America/Sao_Paulo
# RTS_DATABASE_URL=postgresql+psycopg://usuario:senha@host:5432/rts
# RTS_PUBLIC_URL=http://servidor:$EffectivePort
"@
    # UTF-8 without BOM (Windows PowerShell 5.1 would add one with Set-Content -Encoding UTF8).
    [IO.File]::WriteAllText($EnvFile, $content, (New-Object Text.UTF8Encoding $false))
    Info "Configuração criada em $EnvFile"
} else {
    Info "Mantendo a configuração existente em $EnvFile"
    if ($EffectivePort -ne $CurrentPort) {
        Set-EnvValue "RTS_PORT" "$EffectivePort"
        Info "Porta alterada de $CurrentPort para $EffectivePort em $EnvFile"
    }
}

Set-EnvValue "RTS_INSTALL_TYPE" $Mode

# Updater used by "Atualizar" in the web interface. It runs from the scheduled task
# "RTS Update" (outside the RTS processes, which it stops). Order: download the new
# version while the RTS still runs, then stop it, back up the database, install and
# wait for the new API. Each step is appended to data\update-progress.log, which the
# web interface shows while the update runs.
$updater = @'
# Atualizador do Real Task Scheduler - iniciado pela tarefa agendada "RTS Update".
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$InstallDir = $PSScriptRoot
$Data = Join-Path $InstallDir "data"
$RequestFile = Join-Path $Data "update-request.json"
$ResultFile = Join-Path $Data "update-result.json"
$ProgressFile = Join-Path $Data "update-progress.log"
$EnvFile = Join-Path $InstallDir ".env"
if (-not (Test-Path $RequestFile)) { exit 0 }
$req = Get-Content $RequestFile -Raw | ConvertFrom-Json
Remove-Item $RequestFile -Force
$script:Step = "start"

function Progress([string] $step, [string] $status, [string] $detail = "") {
    $script:Step = $step
    $event = [ordered]@{ step = $step; status = $status; at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'") }
    if ($detail) { $event.detail = $detail }
    try {
        [IO.File]::AppendAllText($ProgressFile, (($event | ConvertTo-Json -Compress) + "`n"), (New-Object Text.UTF8Encoding $false))
    } catch { }
}

function Save-Result([bool] $ok, [string] $message) {
    $json = @{ ok = $ok; version = $req.version; from_version = $req.from_version; requested_at = $req.requested_at;
               finished_at = (Get-Date).ToUniversalTime().ToString("o"); message = $message } | ConvertTo-Json
    [IO.File]::WriteAllText($ResultFile, $json, (New-Object Text.UTF8Encoding $false))
}

function Get-EnvValue([string] $key) {
    $line = (Get-Content $EnvFile -ErrorAction SilentlyContinue) -match "^$key=" | Select-Object -Last 1
    if ($line) { return ($line -replace "^$key=", "").Trim() }
    return ""
}

function Format-Mb([double] $bytes) { return "{0:N1}" -f ($bytes / 1MB) }

function Get-WithProgress([string] $url, [string] $target, [string] $name) {
    # Downloads in the background and reports "x de y MB" every 2 seconds.
    if (Test-Path $target) { Remove-Item $target -Force }
    $total = 0
    try { $total = [int64] ((Invoke-WebRequest $url -Method Head -UseBasicParsing).Headers["Content-Length"] | Select-Object -First 1) } catch { }
    $curl = Join-Path $env:SystemRoot "System32\curl.exe"
    if (-not (Test-Path $curl)) {
        Progress "download" "running" "$name"
        Invoke-WebRequest $url -OutFile $target -UseBasicParsing
        return
    }
    $proc = Start-Process $curl -ArgumentList @("-fsSL", "-o", "`"$target`"", "`"$url`"") -PassThru -WindowStyle Hidden
    $null = $proc.Handle  # keeps ExitCode available after the process ends
    while (-not $proc.HasExited) {
        $got = if (Test-Path $target) { (Get-Item $target).Length } else { 0 }
        $of = if ($total -gt 0) { " de $(Format-Mb $total) MB" } else { " MB" }
        Progress "download" "running" "$name`: $(Format-Mb $got)$of"
        Start-Sleep -Seconds 2
    }
    if ($proc.ExitCode) { throw "falha ao baixar $name (curl código $($proc.ExitCode))" }
}

Start-Transcript -Path (Join-Path $Data "update.log") -Append | Out-Null
$stopped = $false
try {
    Write-Host "Atualizando $($req.from_version) -> $($req.version)"
    Progress "start" "done"
    $version = $req.version
    $plain = $version.TrimStart("v")
    $mode = Get-EnvValue "RTS_INSTALL_TYPE"
    if ($mode -ne "python" -and $mode -ne "standalone") {
        $mode = if (Test-Path (Join-Path $InstallDir "venv\Scripts\python.exe")) { "python" } else { "standalone" }
    }
    $base = "https://github.com/$($req.repo)/releases/download/$version"

    # 1. Download while the RTS keeps running: a failure here interrupts nothing.
    Progress "download" "running" "install.ps1"
    $installer = Join-Path $env:TEMP "rts-install-$version.ps1"
    Invoke-WebRequest "$base/install.ps1" -OutFile $installer -UseBasicParsing
    $asset = if ($mode -eq "python") { "rts-$plain-py3-none-any.whl" } else { "rts-$plain-windows-x64.zip" }
    $package = Join-Path $env:TEMP $asset
    Get-WithProgress "$base/$asset" $package $asset
    Progress "download" "done" "$asset ($(Format-Mb (Get-Item $package).Length) MB)"

    # 2. Stop the RTS.
    Progress "stop" "running"
    Stop-ScheduledTask "RTS Worker" -ErrorAction SilentlyContinue
    Stop-ScheduledTask "RTS API" -ErrorAction SilentlyContinue
    $stopped = $true
    Start-Sleep -Seconds 3
    Progress "stop" "done"

    # 3. Back up the SQLite database.
    Progress "backup" "running"
    $backups = Join-Path $Data "backups"
    New-Item -ItemType Directory -Force -Path $backups | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $copied = 0
    foreach ($f in "rts.db", "rts.db-wal", "rts.db-shm") {
        $src = Join-Path $Data $f
        if (Test-Path $src) {
            Copy-Item $src (Join-Path $backups ($f -replace "^rts", "rts-$($req.from_version)-$stamp"))
            $copied++
        }
    }
    $backupNote = if ($copied) { "data\backups\rts-$($req.from_version)-$stamp.db" } else { "sem banco SQLite local (nada a copiar)" }
    Progress "backup" "done" $backupNote

    # 4. Install. The installer is UTF-8 without BOM (required by "irm | iex"); "-File"
    # would read it as ANSI on Windows PowerShell 5.1, so load it explicitly as UTF-8 in a
    # child process. It reports its own progress through RTS_UPDATE_PROGRESS.
    Progress "install" "running" "modo $mode"
    $env:RTS_UPDATE_PROGRESS = $ProgressFile
    $run = "& ([scriptblock]::Create([IO.File]::ReadAllText('$installer', [Text.Encoding]::UTF8))) " +
           "-Version '$version' -InstallDir '$InstallDir' -Mode '$mode' -Repo '$($req.repo)' -From '$package'"
    & powershell -NoProfile -ExecutionPolicy Bypass -Command $run *>&1 | Out-Host
    if ($LASTEXITCODE) { throw "o instalador terminou com código $LASTEXITCODE" }
    Progress "install" "done"

    # 5. Wait for the new API (the installer already started the scheduled tasks).
    Progress "restart" "running" "aguardando a API responder"
    $port = Get-EnvValue "RTS_PORT"
    if (-not $port) { $port = "8000" }
    $up = $false
    for ($i = 0; $i -lt 90 -and -not $up; $i++) {
        try { $up = (Invoke-RestMethod "http://127.0.0.1:$port/api/v1/health" -TimeoutSec 3).version -eq $plain } catch { }
        if (-not $up) { Start-Sleep -Seconds 1 }
    }
    if (-not $up) { throw "a nova versão foi instalada, mas a API não respondeu em 90 s na porta $port" }
    Progress "restart" "done" "versão $plain respondendo na porta $port"
    Save-Result $true "Atualizado para $version."
} catch {
    Progress $script:Step "failed" "$_"
    Save-Result $false "Falha na atualização: $_ (veja data\update.log)"
    if ($stopped) {
        Start-ScheduledTask "RTS API" -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        Start-ScheduledTask "RTS Worker" -ErrorAction SilentlyContinue
    }
} finally {
    Stop-Transcript | Out-Null
}
'@
[IO.File]::WriteAllText((Join-Path $InstallDir "update.ps1"), $updater, (New-Object Text.UTF8Encoding $true))

# Wrapper so "rts.cmd <comando>" always runs with the installation's configuration.
$wrapper = Join-Path $InstallDir "rts.cmd"
@"
@echo off
cd /d "%~dp0"
"$Runner" %*
"@ | Set-Content -Path $wrapper -Encoding ASCII

# Admin password: set through the CLI, so it is never stored in plain text in .env.
if ($FreshInstall) {
    Push-Location $InstallDir
    # Windows PowerShell 5.1 turns any stderr line of a native program into a terminating
    # error under "Stop"; log lines on stderr are expected here.
    $ErrorActionPreference = "Continue"
    try {
        $resetArgs = @("admin", "reset-password")
        if ($AdminPassword) { $resetArgs += @("--password", $AdminPassword) }
        $out = & $Runner @resetArgs 2>&1 | Out-String
        if ($LASTEXITCODE) { Fail "Falha ao preparar o banco de dados:`n$out" }
        if (-not $AdminPassword -and $out -match "redefinida: (\S+)") { $GeneratedPassword = $Matches[1] }
    } finally { Pop-Location; $ErrorActionPreference = "Stop" }
}

# ------------------------------------------------------------------ service
Report-Progress "install" "done"
Report-Progress "restart" "running" "registrando e iniciando as tarefas agendadas"
$ServiceOk = $false
if (-not $NoService) {
    if (-not $IsAdmin) {
        Warn "Para iniciar com o Windows, execute este script no PowerShell como Administrador (ou use -NoService)."
    } else {
        Info "Registrando no Agendador de Tarefas (inicia com o Windows, conta SYSTEM)..."
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -StartWhenAvailable -MultipleInstances IgnoreNew
        $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
        $trigger = New-ScheduledTaskTrigger -AtStartup
        foreach ($pair in @(@("RTS API", "api"), @("RTS Worker", "worker"))) {
            $action = New-ScheduledTaskAction -Execute $Runner -Argument $pair[1] -WorkingDirectory $InstallDir
            Register-ScheduledTask -TaskName $pair[0] -Action $action -Trigger $trigger -Settings $settings `
                -Principal $principal -Description "Real Task Scheduler ($($pair[1]))" -Force | Out-Null
        }
        # On-demand updater task (no trigger: started by the API through "schtasks /Run").
        # Not re-registered while it runs (it is what runs this script during an update).
        $updateTask = Get-ScheduledTask -TaskName "RTS Update" -ErrorAction SilentlyContinue
        if (-not $updateTask -or $updateTask.State -ne "Running") {
            $updateAction = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $InstallDir `
                -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $InstallDir 'update.ps1')`""
            $updateSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
            Register-ScheduledTask -TaskName "RTS Update" -Action $updateAction -Settings $updateSettings `
                -Principal $principal -Description "Real Task Scheduler (atualizador)" -Force | Out-Null
        }
        # The web interface offers "Atualizar" only when the updater task exists.
        Set-EnvValue "RTS_UPDATER" "windows-task"
        Start-ScheduledTask -TaskName "RTS API"
        Start-Sleep -Seconds 4
        Start-ScheduledTask -TaskName "RTS Worker"
        $ServiceOk = $true
    }
}
if (-not $ServiceOk) { Set-EnvValue "RTS_UPDATER" "" }

# ------------------------------------------------------------------ summary
$url = "http://localhost:$EffectivePort"
if ($ServiceOk) {
    Info "Aguardando o RTS responder em $url ..."
    $up = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-RtsOnPort $EffectivePort) { $up = $true; break }
        Start-Sleep 1
    }
    if (-not $up) {
        Warn ("O RTS ainda não respondeu na porta $EffectivePort. Veja os logs com: `"$wrapper`" api`n" +
              "       Se a porta foi ocupada por outro programa, troque RTS_PORT em $EnvFile e reinicie a tarefa 'RTS API'.")
    }
}

Write-Host ""
Write-Host "Real Task Scheduler instalado em $InstallDir" -ForegroundColor Green
Write-Host "  Interface:     $url"
Write-Host "  Usuário:       admin"
if ($GeneratedPassword) { Write-Host "  Senha:         $GeneratedPassword  (troque no primeiro acesso)" }
Write-Host "  Configuração:  $EnvFile"
if ($ServiceOk) {
    Write-Host "  Serviço:       tarefas agendadas 'RTS API' e 'RTS Worker' (iniciam com o Windows)"
} else {
    Write-Host "  Para iniciar:  `"$wrapper`" start"
}
Write-Host "  Senha perdida: `"$wrapper`" admin reset-password"
Write-Host "  Atualizar:     pela interface (Configurações > Atualizações) ou rodando este instalador de novo"
Write-Host "  Desinstalar:   Unregister-ScheduledTask 'RTS API','RTS Worker','RTS Update'; remova $InstallDir"
