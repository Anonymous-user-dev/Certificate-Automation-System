[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $Application,
    [Parameter(Mandatory = $true)]
    [string] $Installer,

    [string] $CertificateThumbprint,
    [string] $TimestampUrl,
    [string] $OutputMetadata = "dist\release-metadata.json",
    [string] $AcceptanceRoot = "dist\acceptance",
    [switch] $RequireSigning
)

$ErrorActionPreference = "Stop"

function Stop-ReleaseSigning([string] $Code, [string] $Message) {
    [Console]::Error.WriteLine("$Code`: $Message")
    exit 2
}

function Find-SignTool {
    $command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path -LiteralPath $kits) {
        return Get-ChildItem -LiteralPath $kits -Filter "signtool.exe" -File -Recurse |
            Where-Object { $_.DirectoryName -match '\\x64$' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }
    return $null
}

if ($RequireSigning -and [string]::IsNullOrWhiteSpace($CertificateThumbprint)) {
    Stop-ReleaseSigning "SIGNING_CERTIFICATE_REQUIRED" "Provide -CertificateThumbprint when -RequireSigning is used."
}

if (-not [string]::IsNullOrWhiteSpace($CertificateThumbprint)) {
    $thumbprint = ($CertificateThumbprint -replace '\s', '').ToUpperInvariant()
    $certificate = Get-ChildItem -LiteralPath "Cert:\CurrentUser\My\$thumbprint" -ErrorAction SilentlyContinue
    if (-not $certificate) {
        Stop-ReleaseSigning "SIGNING_CERTIFICATE_NOT_FOUND" "No matching certificate exists in Cert:\CurrentUser\My."
    }
    if (-not $certificate.HasPrivateKey) {
        Stop-ReleaseSigning "SIGNING_PRIVATE_KEY_REQUIRED" "The configured certificate has no accessible private key."
    }
    $signTool = Find-SignTool
    if (-not $signTool) {
        Stop-ReleaseSigning "SIGNTOOL_NOT_FOUND" "Install the Windows 10/11 SDK signing tools (x64)."
    }
    foreach ($path in @($Application, $Installer)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            Stop-ReleaseSigning "RELEASE_ARTIFACT_MISSING" "Artifact was not found: $path"
        }
        $arguments = @("sign", "/sha1", $thumbprint, "/fd", "SHA256")
        if (-not [string]::IsNullOrWhiteSpace($TimestampUrl)) {
            $arguments += @("/tr", $TimestampUrl, "/td", "SHA256")
        }
        $arguments += $path
        & $signTool @arguments
        if ($LASTEXITCODE -ne 0) {
            Stop-ReleaseSigning "SIGNTOOL_FAILED" "SignTool rejected artifact: $path"
        }
    }
}

$verify = Join-Path $PSScriptRoot "verify-release.ps1"
$verifyArguments = @{
    Application = $Application
    Installer = $Installer
    OutputMetadata = $OutputMetadata
    AcceptanceRoot = $AcceptanceRoot
}
if ($CertificateThumbprint) { $verifyArguments.ExpectedThumbprint = $CertificateThumbprint }
if ($RequireSigning) { $verifyArguments.RequireSigning = $true }
& $verify @verifyArguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
