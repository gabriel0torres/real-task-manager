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
function Warn($msg) { Write-Host "AVISO: $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "ERRO: $msg" -ForegroundColor Red; exit 1 }

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $InstallDir) {
    $InstallDir = if ($IsAdmin) { Join-Path $env:ProgramData "RTS" } else { Join-Path $env:LOCALAPPDATA "RTS" }
}
$Arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { Fail "Somente Windows 64 bits é suportado." }

# ------------------------------------------------------------------ python
function Find-Python {
    $candidates = @(
        @{ exe = "py"; args = @("-3") },
        @{ exe = "python"; args = @() },
        @{ exe = "python3"; args = @() }
    )
    # Run each candidate: the Microsoft Store placeholder ("python" with no Python installed)
    # just prints a message and fails, while real installs (including the Python Install
    # Manager aliases in WindowsApps) answer the version check.
    $ErrorActionPreference = "Continue"
    foreach ($c in $candidates) {
        $cmd = Get-Command $c.exe -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            $ok = & $cmd.Source @($c.args + @("-c", "import sys, venv; print(sys.version_info >= (3, 12))")) 2>$null
            if ("$ok".Trim() -eq "True") { $ErrorActionPreference = "Stop"; return @{ exe = $cmd.Source; args = $c.args } }
        } catch { }
    }
    $ErrorActionPreference = "Stop"
    return $null
}

$Python = Find-Python
if ($From) {
    if (-not (Test-Path $From)) { Fail "Arquivo não encontrado: $From" }
    $From = (Resolve-Path $From).Path
    if ($Mode -eq "auto") { $Mode = if ($From -like "*.whl") { "python" } else { "standalone" } }
}
if ($Mode -eq "auto") { $Mode = if ($Python) { "python" } else { "standalone" } }
if ($Mode -eq "python" -and -not $Python) { Fail "Python 3.12+ não encontrado. Instale-o ou use -Mode standalone." }
Info "Modo de instalação: $Mode  |  diretório: $InstallDir"

# ------------------------------------------------------------------ download
function Get-Artifact([string] $pattern) {
    if ($From) { return $From }
    $api = if ($Version -eq "latest") { "https://api.github.com/repos/$Repo/releases/latest" }
           else { "https://api.github.com/repos/$Repo/releases/tags/$Version" }
    Info "Consultando versões em github.com/$Repo ..."
    try { $release = Invoke-RestMethod $api -Headers @{ "User-Agent" = "rts-installer" } }
    catch { Fail "Não foi possível obter a versão '$Version' de $Repo. Há uma Release publicada? ($_)" }
    $asset = $release.assets | Where-Object { $_.name -like $pattern } | Select-Object -First 1
    if (-not $asset) { Fail "A versão $($release.tag_name) não tem o arquivo $pattern." }
    $target = Join-Path $env:TEMP $asset.name
    Info "Baixando $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) MB)..."
    Invoke-WebRequest $asset.browser_download_url -OutFile $target -UseBasicParsing
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
    if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
        Info "Criando ambiente virtual..."
        & $Python.exe @($Python.args + @("-m", "venv", $venv))
        if ($LASTEXITCODE) { Fail "Falha ao criar o ambiente virtual." }
    }
    $vpy = Join-Path $venv "Scripts\python.exe"
    Info "Instalando o pacote (pode levar alguns minutos)..."
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
# "RTS Update" (outside the RTS processes, which it stops), backs up the database and
# runs the installer of the requested version.
$updater = @'
# Atualizador do Real Task Scheduler - iniciado pela tarefa agendada "RTS Update".
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$InstallDir = $PSScriptRoot
$Data = Join-Path $InstallDir "data"
$RequestFile = Join-Path $Data "update-request.json"
$ResultFile = Join-Path $Data "update-result.json"
if (-not (Test-Path $RequestFile)) { exit 0 }
$req = Get-Content $RequestFile -Raw | ConvertFrom-Json
Remove-Item $RequestFile -Force

function Save-Result([bool] $ok, [string] $message) {
    $json = @{ ok = $ok; version = $req.version; from_version = $req.from_version;
               finished_at = (Get-Date).ToUniversalTime().ToString("o"); message = $message } | ConvertTo-Json
    [IO.File]::WriteAllText($ResultFile, $json, (New-Object Text.UTF8Encoding $false))
}

Start-Transcript -Path (Join-Path $Data "update.log") -Append | Out-Null
try {
    Write-Host "Atualizando $($req.from_version) -> $($req.version)"
    Stop-ScheduledTask "RTS Worker" -ErrorAction SilentlyContinue
    Stop-ScheduledTask "RTS API" -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    $backups = Join-Path $Data "backups"
    New-Item -ItemType Directory -Force -Path $backups | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    foreach ($f in "rts.db", "rts.db-wal", "rts.db-shm") {
        $src = Join-Path $Data $f
        if (Test-Path $src) { Copy-Item $src (Join-Path $backups ($f -replace "^rts", "rts-$($req.from_version)-$stamp")) }
    }
    $mode = ((Get-Content (Join-Path $InstallDir ".env")) -match "^RTS_INSTALL_TYPE=" | Select-Object -First 1) -replace "^RTS_INSTALL_TYPE=", ""
    if (-not $mode) { $mode = "auto" }
    $installer = Join-Path $env:TEMP "rts-install-$($req.version).ps1"
    Invoke-WebRequest "https://github.com/$($req.repo)/releases/download/$($req.version)/install.ps1" -OutFile $installer -UseBasicParsing
    # The installer is UTF-8 without BOM (required by "irm | iex"); "-File" would read it as
    # ANSI on Windows PowerShell 5.1, so load it explicitly as UTF-8 in a child process.
    # Out-Host sends its output into the transcript (data\update.log).
    $run = "& ([scriptblock]::Create([IO.File]::ReadAllText('$installer', [Text.Encoding]::UTF8))) " +
           "-Version '$($req.version)' -InstallDir '$InstallDir' -Mode '$mode' -Repo '$($req.repo)'"
    & powershell -NoProfile -ExecutionPolicy Bypass -Command $run *>&1 | Out-Host
    if ($LASTEXITCODE) { throw "o instalador terminou com código $LASTEXITCODE" }
    Save-Result $true "Atualizado para $($req.version)."
} catch {
    Save-Result $false "Falha na atualização: $_ (veja data\update.log)"
    Start-ScheduledTask "RTS API" -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Start-ScheduledTask "RTS Worker" -ErrorAction SilentlyContinue
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
