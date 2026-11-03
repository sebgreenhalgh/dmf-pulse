[CmdletBinding()]
param(
    [ValidateSet('start','install-reviewed-update','rollback-reviewed-update','withdraw-standing','gw10-diagnostic-paid','gw10-diagnostic-read-only','inspect-gw10-diagnostic','reconcile-gw10-prior-usage')][string]$Action = 'start',
    [string]$Carrier,
    [string]$ReleaseId,
    [string]$SessionKey
)
$ErrorActionPreference = 'Stop'
if ($args.Count -ne 0) { throw 'OPERATOR_ARGUMENTS_NOT_ALLOWED' }
if ($SessionKey -and $Action -ne 'inspect-gw10-diagnostic') { throw 'OPERATOR_ARGUMENTS_NOT_ALLOWED' }
$operatorArguments = @('start')
switch ($Action) {
    'start' { if ($Carrier -or $ReleaseId) { throw 'OPERATOR_ARGUMENTS_NOT_ALLOWED' } }
    'install-reviewed-update' {
        if (-not $Carrier -or $ReleaseId -or -not [IO.Path]::IsPathRooted($Carrier)) { throw 'ABSOLUTE_REVIEWED_CARRIER_REQUIRED' }
        $operatorArguments = @('operation','install-reviewed-update',$Carrier)
    }
    'rollback-reviewed-update' {
        if ($Carrier -or $ReleaseId -cnotmatch '^[0-9a-f]{64}$') { throw 'RETAINED_RELEASE_ID_REQUIRED' }
        $operatorArguments = @('operation','rollback-reviewed-update',$ReleaseId)
    }
    'withdraw-standing' {
        if ($Carrier -or $ReleaseId) { throw 'OPERATOR_ARGUMENTS_NOT_ALLOWED' }
        $operatorArguments = @('operation','withdraw-standing')
    }
    'gw10-diagnostic-paid' {
        if ($Carrier -or $ReleaseId) { throw 'OPERATOR_ARGUMENTS_NOT_ALLOWED' }
        $operatorArguments = @('operation','gw10-diagnostic-paid')
    }
    'gw10-diagnostic-read-only' {
        if ($Carrier -or $ReleaseId) { throw 'OPERATOR_ARGUMENTS_NOT_ALLOWED' }
        $operatorArguments = @('operation','gw10-diagnostic-read-only')
    }
    'inspect-gw10-diagnostic' {
        if ($Carrier -or $ReleaseId -or $SessionKey -cnotmatch '^[0-9a-f]{64}$') { throw 'EXACT_DIAGNOSTIC_SESSION_REQUIRED' }
        $operatorArguments = @('operation','inspect-gw10-diagnostic',$SessionKey)
    }
    'reconcile-gw10-prior-usage' {
        if ($Carrier -or $ReleaseId -or $SessionKey) { throw 'OPERATOR_ARGUMENTS_NOT_ALLOWED' }
        $operatorArguments = @('operation','reconcile-gw10-prior-usage')
    }
}
$operatorLocal = [Environment]::GetFolderPath('LocalApplicationData')
$operatorRoot = Join-Path $operatorLocal 'DMFPulse\operator'
$operatorPython = Join-Path $operatorLocal 'DMFPulse\gw10\venv\Scripts\python.exe'
$operatorHost = Split-Path (Split-Path $operatorPython)
if ((Get-FileHash -LiteralPath (Join-Path $operatorHost 'pyvenv.cfg') -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'fd505d93d8c7e1e7589de8e6dbab3d86664f282b9ebbfe107a8e854c8daacd0f') {
    throw 'REVIEWED_HOST_INTERPRETER_SELECTION_REQUIRED'
}
if (Test-Path -LiteralPath (Join-Path $operatorHost 'Scripts\pyvenv.cfg')) { throw 'INTERPRETER_SELECTION_OVERRIDE_DENIED' }
$operatorBase = Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'uv\python\cpython-3.13.5-windows-x86_64-none'
foreach ($operatorDirectory in @($operatorHost,(Join-Path $operatorHost 'Scripts'),$operatorBase)) {
    if (@(Get-ChildItem -LiteralPath $operatorDirectory -Filter '*._pth' -Force).Count -ne 0) { throw 'INTERPRETER_SELECTION_OVERRIDE_DENIED' }
}
foreach ($operatorSelection in @((Join-Path $operatorBase 'pyvenv.cfg'),(Join-Path (Split-Path $operatorBase) 'pyvenv.cfg'))) {
    if (Test-Path -LiteralPath $operatorSelection) { throw 'INTERPRETER_SELECTION_OVERRIDE_DENIED' }
}
$operatorPlatform = @{
    'python.exe' = 'b8384375abd729aa2701093a22f926f28bc31f6ff8f406d1d6e3342cb72e40fd'
    'python313.dll' = 'e1ff5878af41e21bf64b9916ed6735ca30ce48623e3d941fdd1460a541611596'
    'python3.dll' = '40039942e112e8d252a676940d802a93bc98d681880d6326147f4a4da772bfb7'
}
foreach ($operatorBinary in $operatorPlatform.Keys) {
    if ((Get-FileHash -LiteralPath (Join-Path $operatorBase $operatorBinary) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $operatorPlatform[$operatorBinary]) { throw 'REVIEWED_OWNER_PYTHON_PLATFORM_REQUIRED' }
}
if ((Get-FileHash -LiteralPath $operatorPython -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'bc2669ce1086d0c634ea148395df9f029da828793f0aabf6e0e7eb326a0f4c0c') {
    throw 'REVIEWED_OWNER_PYTHON_REQUIRED'
}
& (Join-Path $operatorBase 'python.exe') -I -S -B (Join-Path $operatorRoot 'launch_start.py') @operatorArguments
exit $LASTEXITCODE
