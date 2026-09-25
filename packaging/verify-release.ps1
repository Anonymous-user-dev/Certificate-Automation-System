[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [Alias("Input")]
    [string[]] $Artifact,

    [string] $OutputMetadata = "dist\release-metadata.json",
    [string] $ExpectedThumbprint,
    [string] $AcceptanceRoot = "dist\acceptance",
    [switch] $RequireSigning
)

$ErrorActionPreference = "Stop"
$script:ReleaseVersion = "3.0.0"
$securityModule = Join-Path $PSHOME "Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1"
if (Test-Path -LiteralPath $securityModule) { Import-Module $securityModule -Force }

function Stop-ReleaseVerification([string] $Code, [string] $Message) {
    [Console]::Error.WriteLine("$Code`: $Message")
    exit 2
}

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

function Get-MatrixState([string] $InstallerHash) {
    $targets = @(
        [ordered]@{ os = "Windows 10"; release = "22H2" },
        [ordered]@{ os = "Windows 11"; release = "24H2" },
        [ordered]@{ os = "Windows 11"; release = "25H2" }
    )
    $evidence = @()
    if (Test-Path -LiteralPath $AcceptanceRoot -PathType Container) {
        foreach ($file in Get-ChildItem -LiteralPath $AcceptanceRoot -Filter "acceptance.json" -File -Recurse) {
            try { $evidence += Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json } catch { }
        }
    }
    foreach ($target in $targets) {
        $matching = $evidence | Where-Object {
            $_.target.os -eq $target.os -and
            $_.target.release -eq $target.release -and
            $_.installer.sha256 -eq $InstallerHash -and
            $_.overall_status -eq "passed"
        } | Select-Object -First 1
        $target.state = if ($null -ne $matching) { "verified" } else { "machine_verification_pending" }
        $target.evidence = if ($null -ne $matching) { [string]$matching.evidence_id } else { $null }
    }
    return $targets
}

$resolved = @()
foreach ($candidate in $Artifact) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        Stop-ReleaseVerification "RELEASE_ARTIFACT_MISSING" "Artifact was not found: $candidate"
    }
    $resolved += (Resolve-Path -LiteralPath $candidate).ProviderPath
}
if ($resolved.Count -ne ($resolved | Select-Object -Unique).Count) {
    Stop-ReleaseVerification "DUPLICATE_RELEASE_ARTIFACT" "Each artifact must be provided exactly once."
}

$expected = Normalize-Thumbprint $ExpectedThumbprint
$artifacts = @()
foreach ($path in $resolved) {
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    $isValid = [string]$signature.Status -eq "Valid"
    $thumbprint = if ($signature.SignerCertificate) { Normalize-Thumbprint $signature.SignerCertificate.Thumbprint } else { $null }
    $publisher = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
    if ($isValid -and $expected -and $thumbprint -ne $expected) {
        Stop-ReleaseVerification "SIGNER_THUMBPRINT_MISMATCH" "The signer certificate does not match the configured thumbprint: $path"
    }
    if ($RequireSigning -and -not $isValid) {
        Stop-ReleaseVerification "SIGNATURE_REQUIRED" "Artifact is not signed with a valid Authenticode signature: $path"
    }
    $item = Get-Item -LiteralPath $path
    $artifacts += [ordered]@{
        path = $item.FullName
        size = [long]$item.Length
        sha256 = Get-Sha256 $path
        signature_status = if ($isValid) { "signed" } else { "unsigned" }
        authenticode_status = [string]$signature.Status
        publisher = $publisher
        thumbprint = $thumbprint
    }
}

$signed = @($artifacts | Where-Object { $_.signature_status -eq "signed" })
$overallSignature = if ($signed.Count -eq $artifacts.Count) { "signed" } elseif ($signed.Count -eq 0) { "unsigned" } else { "mixed" }
$publisher = if ($overallSignature -eq "signed" -and ($artifacts.publisher | Select-Object -Unique).Count -eq 1) { $artifacts[0].publisher } else { $null }
$installer = $artifacts | Where-Object { [IO.Path]::GetFileName($_.path) -like "*Setup*.exe" } | Select-Object -First 1
$installerHash = if ($installer) { $installer.sha256 } else { $null }

$metadata = [ordered]@{
    schema_version = 1
    release_version = $script:ReleaseVersion
    generated_utc = [DateTime]::UtcNow.ToString("o")
    architecture = "x64"
    offline_runtime = $true
    signature_status = $overallSignature
    publisher = $publisher
    artifacts = $artifacts
    windows_matrix = @(Get-MatrixState $installerHash)
}

$parent = Split-Path -Parent $OutputMetadata
if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
$metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputMetadata -Encoding UTF8
[Console]::Out.WriteLine((Resolve-Path -LiteralPath $OutputMetadata).Path)
