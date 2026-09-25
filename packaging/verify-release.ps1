[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $Application,
    [Parameter(Mandatory = $true)] [string] $Installer,
    [string] $OutputMetadata = "dist\release-metadata.json",
    [string] $ExpectedThumbprint,
    [string] $AcceptanceRoot = "dist\acceptance",
    [switch] $RequireSigning
)

$ErrorActionPreference = "Stop"
$script:ReleaseVersion = "3.0.0"
$securityModule = Join-Path $PSHOME "Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1"
if (Test-Path -LiteralPath $securityModule) { Import-Module $securityModule -Force }

function Stop-ReleaseVerification([string] $Code, [string] $Message) { [Console]::Error.WriteLine("$Code`: $Message"); exit 2 }
function Normalize-Thumbprint([string] $Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    return ($Value -replace '\s', '').ToUpperInvariant()
}
function Get-Sha256([string] $Path) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream)) -replace '-', '').ToLowerInvariant() }
        finally { $algorithm.Dispose() }
    } finally { $stream.Dispose() }
}
function Assert-PeX64([string] $Path) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $reader = New-Object IO.BinaryReader($stream)
        try {
            if ($reader.ReadUInt16() -ne 0x5A4D) { Stop-ReleaseVerification "RELEASE_APPLICATION_PE_INVALID" "Application has no DOS/PE header." }
            $stream.Position = 0x3C
            $peOffset = $reader.ReadInt32()
            if ($peOffset -lt 0 -or $peOffset -gt ($stream.Length - 6)) { Stop-ReleaseVerification "RELEASE_APPLICATION_PE_INVALID" "Application PE offset is invalid." }
            $stream.Position = $peOffset
            if ($reader.ReadUInt32() -ne 0x00004550) { Stop-ReleaseVerification "RELEASE_APPLICATION_PE_INVALID" "Application PE signature is invalid." }
            if ($reader.ReadUInt16() -ne 0x8664) { Stop-ReleaseVerification "RELEASE_APPLICATION_ARCHITECTURE_INVALID" "Application is not PE x64." }
        } finally { $reader.Dispose() }
    } finally { $stream.Dispose() }
}
function Assert-Version([string] $Path, [string] $Kind) {
    $version = [string](Get-Item -LiteralPath $Path).VersionInfo.ProductVersion
    if ($version -notmatch '^3\.0\.0(?:\.0)?(?:\s|$)') { Stop-ReleaseVerification "RELEASE_VERSION_INVALID" "$Kind ProductVersion must be 3.0.0; measured '$version'." }
}

if ($RequireSigning -and [string]::IsNullOrWhiteSpace($ExpectedThumbprint)) {
    Stop-ReleaseVerification "SIGNING_EXPECTED_THUMBPRINT_REQUIRED" "Required signing must pin the expected certificate thumbprint."
}
if (-not (Test-Path -LiteralPath $Application -PathType Leaf)) { Stop-ReleaseVerification "RELEASE_APPLICATION_MISSING" "Application was not found: $Application" }
if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) { Stop-ReleaseVerification "RELEASE_INSTALLER_MISSING" "Installer was not found: $Installer" }
$applicationPath = (Resolve-Path -LiteralPath $Application).ProviderPath
$installerPath = (Resolve-Path -LiteralPath $Installer).ProviderPath
if ([IO.Path]::GetFileName($applicationPath) -cne "CertificateAutomation.exe") { Stop-ReleaseVerification "RELEASE_APPLICATION_NAME_INVALID" "Expected CertificateAutomation.exe." }
if ([IO.Path]::GetFileName($installerPath) -cne "CertificateAutomation-Setup-3.0.0.exe") { Stop-ReleaseVerification "RELEASE_INSTALLER_NAME_INVALID" "Expected CertificateAutomation-Setup-3.0.0.exe." }

Assert-PeX64 $applicationPath
Assert-Version $applicationPath "Application"
Assert-Version $installerPath "Installer"
$installerBytes = [IO.File]::ReadAllBytes($installerPath)
$installerText = [Text.Encoding]::ASCII.GetString($installerBytes) + [Text.Encoding]::Unicode.GetString($installerBytes)
if (-not $installerText.Contains("Inno Setup Setup Data")) { Stop-ReleaseVerification "RELEASE_INSTALLER_FORMAT_INVALID" "Installer is not an Inno Setup release artifact." }
$applicationBytes = [IO.File]::ReadAllBytes($applicationPath)
$manifestText = [Text.Encoding]::UTF8.GetString($applicationBytes) + [Text.Encoding]::Unicode.GetString($applicationBytes)
foreach ($required in @("8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a", "longPathAware", 'level="asInvoker"')) {
    if (-not $manifestText.Contains($required)) { Stop-ReleaseVerification "RELEASE_MANIFEST_INVALID" "Embedded manifest is missing '$required'." }
}
$bundleRoot = Split-Path -Parent $applicationPath
$internal = Join-Path $bundleRoot "_internal"
foreach ($relative in @(
    "certificate_automation\locales\en.json", "certificate_automation\locales\ru.json",
    "certificate_automation\locales\zh_CN.json", "examples\sample_recipients.csv",
    "examples\sample_students.xlsx", "examples\sample_certificate_template.docx"
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $internal $relative) -PathType Leaf)) { Stop-ReleaseVerification "OFFLINE_BUNDLE_INCOMPLETE" "Offline bundle is missing: $relative" }
}
if (@(Get-ChildItem -LiteralPath $internal -Filter "icu*.dll" -File -ErrorAction SilentlyContinue).Count) { Stop-ReleaseVerification "OFFLINE_BUNDLE_FOREIGN_ICU" "Offline bundle contains an unsupported foreign ICU runtime." }

$expected = Normalize-Thumbprint $ExpectedThumbprint
$artifacts = @()
foreach ($path in @($applicationPath, $installerPath)) {
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    $isValid = [string]$signature.Status -eq "Valid"
    $thumbprint = if ($signature.SignerCertificate) { Normalize-Thumbprint $signature.SignerCertificate.Thumbprint } else { $null }
    $publisher = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
    if ($isValid -and $expected -and $thumbprint -ne $expected) { Stop-ReleaseVerification "SIGNER_THUMBPRINT_MISMATCH" "Signer does not match expected thumbprint: $path" }
    if ($RequireSigning -and -not $isValid) { Stop-ReleaseVerification "SIGNATURE_REQUIRED" "Artifact is not validly signed: $path" }
    $item = Get-Item -LiteralPath $path
    $artifacts += [ordered]@{
        path = $item.FullName; size = [long]$item.Length; sha256 = Get-Sha256 $path
        signature_status = if ($isValid) { "signed" } else { "unsigned" }
        authenticode_status = [string]$signature.Status; publisher = $publisher; thumbprint = $thumbprint
    }
}
$signed = @($artifacts | Where-Object { $_.signature_status -eq "signed" })
$overallSignature = if ($signed.Count -eq 2) { "signed" } elseif ($signed.Count -eq 0) { "unsigned" } else { "mixed" }
$publisher = if ($overallSignature -eq "signed" -and ($artifacts.publisher | Select-Object -Unique).Count -eq 1) { $artifacts[0].publisher } else { $null }
$installerHash = $artifacts[1].sha256
$validator = Join-Path $PSScriptRoot "validate-acceptance.ps1"
$matrixJson = & $validator -AcceptanceRoot $AcceptanceRoot -InstallerHash $installerHash
if ($LASTEXITCODE -ne 0) { Stop-ReleaseVerification "ACCEPTANCE_VALIDATION_FAILED" "Windows acceptance evidence could not be validated." }
$matrix = @($matrixJson | ConvertFrom-Json)

$metadata = [ordered]@{
    schema_version = 1; release_version = $script:ReleaseVersion; generated_utc = [DateTime]::UtcNow.ToString("o")
    architecture = "x64"; offline_runtime = $true; signature_status = $overallSignature; publisher = $publisher
    artifacts = $artifacts; windows_matrix = $matrix
}
$parent = Split-Path -Parent $OutputMetadata
if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
$metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputMetadata -Encoding UTF8
[Console]::Out.WriteLine((Resolve-Path -LiteralPath $OutputMetadata).Path)
