# Run the Windows Electron shell against this checkout's Python and Dashboard.
[CmdletBinding()]
param(
    [switch]$Bot,
    [switch]$NoBuild,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ElectronArgs
)
$ErrorActionPreference = 'Stop'
$shellDir = Split-Path -Parent $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $shellDir '..\..')).Path
$venvDir = Join-Path $repoRoot '.venv'
$python = Join-Path $venvDir 'Scripts\python.exe'
$runtimeDir = Join-Path $shellDir '.dev-runtime\windows'
if (!(Test-Path -LiteralPath $python)) { throw "Run uv sync in $repoRoot first." }

function Ensure-Junction([string]$Link, [string]$Target) {
    $existing = Get-Item -LiteralPath $Link -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        New-Item -ItemType Junction -Path $Link -Target $Target | Out-Null
    } elseif ($existing.LinkType -ne 'Junction' -or $existing.Target -ne $Target) {
        throw "Unexpected dev runtime path: $Link. Expected a junction to $Target."
    }
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
Ensure-Junction (Join-Path $runtimeDir 'runtime') (Join-Path $venvDir 'Scripts')
Ensure-Junction (Join-Path $runtimeDir 'packages') (Join-Path $venvDir 'Lib\site-packages')
Copy-Item -LiteralPath (Join-Path $venvDir 'pyvenv.cfg') -Destination (Join-Path $runtimeDir 'pyvenv.cfg')
Copy-Item -LiteralPath (Join-Path $repoRoot 'desktop\portable\templates\launch.py') -Destination (Join-Path $runtimeDir 'launch.py')
$version = & $python -c "from importlib.metadata import version; print(version('octop'))"
if ($LASTEXITCODE) { throw 'Could not read the Octop version from the project environment.' }
[IO.File]::WriteAllText((Join-Path $runtimeDir 'version.json'), (@{ version = $version } | ConvertTo-Json -Compress))

Push-Location $shellDir
try {
    if (!$NoBuild) {
        & pnpm.cmd run build
        if ($LASTEXITCODE) { throw 'Electron build failed.' }
    }
    if (!(Test-Path -LiteralPath 'out\main\index.js')) { throw 'Build the Electron shell first.' }
    $electron = & node -p "require('electron')"
    if ($LASTEXITCODE -or !(Test-Path -LiteralPath $electron)) { throw 'Electron is unavailable. Run pnpm install in desktop/src.' }
    $botClient = $Bot -or ($ElectronArgs -contains '--octop-bot')
    if (!$env:OCTOP_HOME) {
        $profile = if ($botClient) { 'bot-home' } else { 'home' }
        $env:OCTOP_HOME = Join-Path $runtimeDir $profile
    }
    if ($botClient -and !$env:OCTOP_DASHBOARD_DEV_PORT) { $env:OCTOP_DASHBOARD_DEV_PORT = '5174' }
    $browserProfile = if ($botClient) { 'electron-bot' } else { 'electron' }
    $productArgs = @()
    if ($Bot -and $ElectronArgs -notcontains '--octop-bot') { $productArgs += '--octop-bot' }
    $env:OCTOP_PORTABLE_DIR = $runtimeDir
    $env:OCTOP_DASHBOARD_DEV = '1'
    $env:OCTOP_DASHBOARD_SOURCE = Join-Path $repoRoot 'dashboard'
    $env:OCTOP_DASHBOARD_DIR = Join-Path $repoRoot 'src\octop\dashboard'
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    & $electron $shellDir "--user-data-dir=$(Join-Path $env:OCTOP_HOME $browserProfile)" @productArgs @ElectronArgs | Out-Host
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
