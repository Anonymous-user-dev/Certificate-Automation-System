[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $BundleRoot,
    [string] $InstalledRoot,
    [string] $ExpectedThumbprint,
    [switch] $RequireSigning
)
$ErrorActionPreference = "Stop"
function Stop-PayloadVerification([string] $Code, [string] $Message) {
    throw "$Code`: $Message"
}
function Get-PayloadHash([string] $Path) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)) }
        finally { $algorithm.Dispose() }
    } finally { $stream.Dispose() }
}
$securityModule = Join-Path $PSHOME "Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1"
if (Test-Path -LiteralPath $securityModule) { Import-Module $securityModule -Force }
if ($RequireSigning -and [string]::IsNullOrWhiteSpace($ExpectedThumbprint)) {
    Stop-PayloadVerification "SIGNING_EXPECTED_THUMBPRINT_REQUIRED" "Pin the expected payload signer."
}
if (-not (Test-Path -LiteralPath (Join-Path $BundleRoot "CertificateAutomation.exe") -PathType Leaf)) {
    Stop-PayloadVerification "RELEASE_APPLICATION_MISSING" "Bundle application was not found."
}
$root = (Resolve-Path -LiteralPath $BundleRoot).ProviderPath.TrimEnd('\')
$expected = ($ExpectedThumbprint -replace '\s', '').ToUpperInvariant()
foreach ($file in Get-ChildItem -LiteralPath $root -File -Recurse) {
    $relative = $file.FullName.Substring($root.Length).TrimStart('\')
    $paths = @($file.FullName)
    if ($InstalledRoot) {
        $installed = Join-Path $InstalledRoot $relative
        if (-not (Test-Path -LiteralPath $installed -PathType Leaf)) {
            Stop-PayloadVerification "INSTALLED_PAYLOAD_MISSING" "Installed payload is missing: $relative"
        }
        if ((Get-PayloadHash $file.FullName) -ne (Get-PayloadHash $installed)) {
            Stop-PayloadVerification "INSTALLED_PAYLOAD_HASH_MISMATCH" "Installed payload differs from the verified bundle: $relative"
        }
        $paths += $installed
    }
    if ($RequireSigning -and $relative -eq "CertificateAutomation.exe") {
        foreach ($path in $paths) {
            $signature = Get-AuthenticodeSignature -LiteralPath $path
            if ([string]$signature.Status -ne "Valid") {
                Stop-PayloadVerification "PAYLOAD_SIGNATURE_REQUIRED" "Payload is not validly signed: $path"
            }
            if (-not $signature.SignerCertificate -or ($signature.SignerCertificate.Thumbprint -replace '\s', '').ToUpperInvariant() -ne $expected) {
                Stop-PayloadVerification "SIGNER_THUMBPRINT_MISMATCH" "Payload signer differs from the configured certificate: $path"
            }
        }
    }
}
