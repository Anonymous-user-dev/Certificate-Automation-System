[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $Application,
    [Parameter(Mandatory = $true)]
    [string] $Installer,

    [string] $InstallerCompiler = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",

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

if (-not (Test-Path -LiteralPath $Application -PathType Leaf)) {
    Stop-ReleaseSigning "RELEASE_APPLICATION_MISSING" "Build the application bundle before signing."
}
$applicationPath = (Resolve-Path -LiteralPath $Application).ProviderPath
$bundleRoot = Split-Path -Parent $applicationPath
$signingEnabled = -not [string]::IsNullOrWhiteSpace($CertificateThumbprint)

function Sign-And-VerifyArtifact([string] $Path) {
    $arguments = @("sign", "/sha1", $thumbprint, "/fd", "SHA256")
    if (-not [string]::IsNullOrWhiteSpace($TimestampUrl)) { $arguments += @("/tr", $TimestampUrl, "/td", "SHA256") }
    $arguments += $Path
    $global:LASTEXITCODE = 0
    & $signTool @arguments
    if ($LASTEXITCODE -ne 0) { Stop-ReleaseSigning "SIGNTOOL_FAILED" "SignTool rejected artifact: $Path" }
    & $signTool verify /pa /all $Path
    if ($LASTEXITCODE -ne 0) { Stop-ReleaseSigning "SIGNTOOL_VERIFY_FAILED" "SignTool could not verify artifact: $Path" }
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
    Sign-And-VerifyArtifact $applicationPath
}

# The compiler must consume this verified bundle, never a pre-signing snapshot.
$payloadVerifier = Join-Path $PSScriptRoot "verify-payload.ps1"
$payloadArguments = @{ BundleRoot = $bundleRoot }
if ($signingEnabled) { $payloadArguments.RequireSigning = $true; $payloadArguments.ExpectedThumbprint = $thumbprint }
$LASTEXITCODE = 0
& $payloadVerifier @payloadArguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$installerPath = [IO.Path]::GetFullPath($Installer)
if ([IO.Path]::GetFileName($installerPath) -cne "CertificateAutomation-Setup-3.0.0.exe") {
    Stop-ReleaseSigning "RELEASE_INSTALLER_NAME_INVALID" "Expected CertificateAutomation-Setup-3.0.0.exe."
}
$outputDirectory = Split-Path -Parent $installerPath
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
if (Test-Path -LiteralPath $installerPath) { Remove-Item -LiteralPath $installerPath -Force }
$LASTEXITCODE = 0
& $InstallerCompiler "/DBuildRoot=$bundleRoot" "/O$outputDirectory" "/FCertificateAutomation-Setup-3.0.0" (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    Stop-ReleaseSigning "INSTALLER_BUILD_FAILED" "Inno Setup did not produce the requested installer."
}
if ($signingEnabled) { Sign-And-VerifyArtifact $installerPath }

$verify = Join-Path $PSScriptRoot "verify-release.ps1"
$verifyArguments = @{
    Application = $applicationPath
    Installer = $installerPath
    OutputMetadata = $OutputMetadata
    AcceptanceRoot = $AcceptanceRoot
}
if ($CertificateThumbprint) { $verifyArguments.ExpectedThumbprint = $CertificateThumbprint }
if ($signingEnabled) { $verifyArguments.RequireSigning = $true }
$LASTEXITCODE = 0
& $verify @verifyArguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
