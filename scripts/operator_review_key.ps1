[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][switch]$EngineeringOnly,
    [Parameter(Mandatory=$true)][ValidateSet('Initialize','Sign')][string]$Action,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [string]$SigningBytesPath
)
# Explicit engineering action only. No launcher/start command invokes this script.
# The fixed current-user CSP container never exports a private RSA parameter.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ErrorView = 'NormalView'
$key = $null
try {
    if (-not $EngineeringOnly -or [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'REVIEW_KEY_ENGINEERING_WINDOWS_REQUIRED' }
    $output = [IO.Path]::GetFullPath($OutputPath)
    if ([IO.File]::Exists($output) -or [IO.Directory]::Exists($output)) { throw 'REVIEW_KEY_OUTPUT_EXISTS' }
    $parent = [IO.Path]::GetDirectoryName($output)
    if (-not [IO.Directory]::Exists($parent)) { throw 'REVIEW_KEY_OUTPUT_PARENT_REQUIRED' }
    foreach ($candidate in @($output,$parent,$SigningBytesPath)) {
        if ([string]::IsNullOrEmpty($candidate)) { continue }
        $cursor = [IO.Path]::GetFullPath($candidate)
        while (-not [string]::IsNullOrEmpty($cursor)) {
            if ((Test-Path -LiteralPath $cursor) -and ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'REVIEW_KEY_REPARSE_DENIED' }
            $directory = [IO.Directory]::GetParent($cursor)
            $cursor = if ($null -eq $directory) { $null } else { $directory.FullName }
        }
    }
    $parameters = [Security.Cryptography.CspParameters]::new(24)
    $parameters.KeyContainerName = 'DMFPulse.OperatorReview.RSA3072.v1'
    $parameters.KeyNumber = 2
    $parameters.Flags = [Security.Cryptography.CspProviderFlags]::UseNonExportableKey
    if ($Action -eq 'Sign') {
        $parameters.Flags = [Security.Cryptography.CspProviderFlags]::UseExistingKey
    }
    $key = [Security.Cryptography.RSACryptoServiceProvider]::new(3072,$parameters)
    $key.PersistKeyInCsp = $true
    if ($key.KeySize -ne 3072 -or $key.CspKeyContainerInfo.MachineKeyStore -or $key.CspKeyContainerInfo.Exportable) { throw 'REVIEW_KEY_STORAGE_INVALID' }
    $public = $key.ExportParameters($false)
    if ([Convert]::ToBase64String($public.Exponent) -ne 'AQAB') { throw 'REVIEW_KEY_EXPONENT_INVALID' }
    $publicJson = '{"algorithm":"RSA3072_SHA256_PKCS1_V1_5","exponent":65537,"modulus_b64":"' + [Convert]::ToBase64String($public.Modulus) + '"}'
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $fingerprint = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($publicJson))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
    if ($Action -eq 'Initialize') {
        if (-not [string]::IsNullOrEmpty($SigningBytesPath)) { throw 'REVIEW_KEY_SIGN_INPUT_UNEXPECTED' }
        $result = $publicJson
    } else {
        if ([string]::IsNullOrEmpty($SigningBytesPath)) { throw 'REVIEW_KEY_SIGN_INPUT_REQUIRED' }
        $inputPath = [IO.Path]::GetFullPath($SigningBytesPath)
        $info = [IO.FileInfo]::new($inputPath)
        if (-not $info.Exists -or $info.Length -gt 16384 -or $info.Length -lt 100 -or ($info.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'REVIEW_KEY_SIGN_INPUT_INVALID' }
        $bytes = [IO.File]::ReadAllBytes($inputPath)
        $prefix = [Text.Encoding]::ASCII.GetBytes("DMF-PULSE-OPERATOR-RELEASE-V1`0{")
        for ($index=0; $index -lt $prefix.Length; $index++) {
            if ($bytes[$index] -ne $prefix[$index]) { throw 'REVIEW_KEY_DOMAIN_INVALID' }
        }
        $signature = $key.SignData($bytes,[Security.Cryptography.CryptoConfig]::MapNameToOID('SHA256'))
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $payloadHash = [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').ToLowerInvariant() }
        finally { $sha.Dispose() }
        $result = '{"review_public_key_sha256":"' + $fingerprint + '","schema_version":"operator-engineering-signature-v1","signature_b64":"' + [Convert]::ToBase64String($signature) + '","signing_bytes_sha256":"' + $payloadHash + '"}'
    }
    $stream = [IO.File]::Open($output,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $encoded = [Text.Encoding]::UTF8.GetBytes($result); $stream.Write($encoded,0,$encoded.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
    Write-Output 'REVIEW_KEY_ENGINEERING_ACTION_COMPLETE'
} catch {
    # Never return provider/CSP diagnostics or private filesystem contents.
    Write-Output 'REVIEW_KEY_ENGINEERING_ACTION_REFUSED'
    exit 1
} finally {
    if ($null -ne $key) { $key.Dispose() }
}
