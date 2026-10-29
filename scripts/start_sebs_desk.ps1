param([switch]$Demo, [ValidateRange(1024, 65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$repositoryPath = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $repositoryPath
try {
    $dashboardArguments = @('run', '--frozen', 'dmf', 'dashboard', '--port', "$Port")
    if ($Demo) { $dashboardArguments += '--demo' }
    & uv @dashboardArguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
