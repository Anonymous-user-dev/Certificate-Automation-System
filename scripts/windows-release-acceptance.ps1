[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $Installer,
    [string] $OutputDirectory = "dist\acceptance",
    [ValidateSet("Windows 10", "Windows 11")]
    [string] $TargetOS,
    [string] $TargetRelease,
    [ValidateSet(100, 150, 200)]
    [int] $DisplayScale = 100,
    [string] $PriorInstaller,
    [string] $PythonExecutable = "python",
    [switch] $RecordOnly
)

$ErrorActionPreference = "Stop"
$securityModule = Join-Path $PSHOME "Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1"
if (Test-Path -LiteralPath $securityModule) { Import-Module $securityModule -Force }

function Stop-Acceptance([string] $Code, [string] $Message) {
    [Console]::Error.WriteLine("$Code`: $Message")
    exit 2
}

function Get-Sha256([string] $Path) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream)) -replace '-', '').ToLowerInvariant() }
        finally { $algorithm.Dispose() }
    } finally { $stream.Dispose() }
}

if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    Stop-Acceptance "INSTALLER_NOT_FOUND" "Installer was not found: $Installer"
}
if ([IO.Path]::GetExtension($Installer) -ne ".exe") {
    Stop-Acceptance "INSTALLER_MUST_BE_EXE" "Acceptance requires the exact .exe installer."
}
if (-not [Environment]::Is64BitOperatingSystem) {
    Stop-Acceptance "X64_WINDOWS_REQUIRED" "The release matrix only supports Windows x64."
}

$installerItem = Get-Item -LiteralPath $Installer
$installerHash = Get-Sha256 $installerItem.FullName
$os = Get-CimInstance Win32_OperatingSystem
$computer = Get-CimInstance Win32_ComputerSystem
$wordVersion = $null
try {
    $word = New-Object -ComObject Word.Application
    $wordVersion = [string]$word.Version
    $word.Quit()
    [Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) | Out-Null
} catch { $wordVersion = $null }

$systemDrive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($env:SystemDrive)'"
$osName = if ($TargetOS) { $TargetOS } elseif ($os.Caption -match "Windows 11") { "Windows 11" } else { "Windows 10" }
$release = if ($TargetRelease) { $TargetRelease } else { [string]$os.DisplayVersion }
$evidenceId = "$($osName -replace ' ', '-')-$release-build-$($os.BuildNumber)-scale-$DisplayScale"
$evidenceDirectory = Join-Path $OutputDirectory $evidenceId
New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null

$gateIds = @(
    "silent_clean_install", "responsive_launch", "all_input_families", "save_and_recover",
    "mixed_script_50_recipient_batch", "unicode_and_long_paths", "locked_file_recovery",
    "upgrade_from_2_1_1", "display_scale_100", "display_scale_150", "display_scale_200",
    "silent_uninstall"
)
$results = [ordered]@{}
foreach ($id in $gateIds) { $results[$id] = [ordered]@{ id = $id; status = "not_run"; detail = $null } }

function Invoke-Gate([string] $Id, [scriptblock] $Action) {
    try {
        & $Action
        if ($LASTEXITCODE -ne 0) { throw "Process exited with code $LASTEXITCODE" }
        $results[$Id].status = "passed"
    } catch {
        $results[$Id].status = "failed"
        $results[$Id].detail = $_.Exception.Message
    }
}

if (-not $RecordOnly) {
    $installLog = Join-Path $evidenceDirectory "install.log"
    Invoke-Gate "silent_clean_install" {
        $process = Start-Process -FilePath $installerItem.FullName -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/LOG=$installLog") -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "Installer exit code $($process.ExitCode)" }
    }
    $application = Join-Path $env:LOCALAPPDATA "Programs\CertificateAutomation\CertificateAutomation.exe"
    Invoke-Gate "responsive_launch" { & $application "--ui-smoke-test" }
    Invoke-Gate "all_input_families" { & $PythonExecutable -m pytest "tests/windows/test_release_acceptance.py::test_release_accepts_every_offline_source_family" -q }
    Invoke-Gate "save_and_recover" { & $application "--workflow-smoke-test" }
    Invoke-Gate "mixed_script_50_recipient_batch" { & $PythonExecutable -m pytest "tests/windows/test_release_acceptance.py::test_real_word_publishes_verified_50_recipient_mixed_script_batch" -m word_integration -q }
    Invoke-Gate "unicode_and_long_paths" { & $application "--workflow-smoke-test" }
    Invoke-Gate "locked_file_recovery" { & $PythonExecutable -m pytest "tests/test_recovery.py" -q }
    if ($PriorInstaller) {
        Invoke-Gate "upgrade_from_2_1_1" {
            $prior = Start-Process -FilePath $PriorInstaller -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-") -Wait -PassThru
            if ($prior.ExitCode -ne 0) { throw "Prior installer exit code $($prior.ExitCode)" }
            $upgrade = Start-Process -FilePath $installerItem.FullName -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-") -Wait -PassThru
            if ($upgrade.ExitCode -ne 0) { throw "Upgrade exit code $($upgrade.ExitCode)" }
        }
    } else { $results["upgrade_from_2_1_1"].detail = "Prior installer was not supplied." }
    foreach ($scale in @(100, 150, 200)) {
        $id = "display_scale_$scale"
        if ($scale -eq $DisplayScale) { Invoke-Gate $id { & $application "--ui-smoke-test" } }
        else { $results[$id].detail = "Run this exact installer in a separate session configured to $scale%." }
    }
    $uninstaller = Join-Path $env:LOCALAPPDATA "Programs\CertificateAutomation\unins000.exe"
    Invoke-Gate "silent_uninstall" {
        $process = Start-Process -FilePath $uninstaller -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "Uninstaller exit code $($process.ExitCode)" }
    }
}

$testResults = @($gateIds | ForEach-Object { $results[$_] })
$overall = if ($RecordOnly) { "not_run" } elseif (@($testResults | Where-Object { $_.status -eq "failed" }).Count) { "failed" } elseif (@($testResults | Where-Object { $_.status -ne "passed" }).Count) { "incomplete" } else { "passed" }
$signature = Get-AuthenticodeSignature -LiteralPath $installerItem.FullName
$payload = [ordered]@{
    schema_version = 1
    evidence_id = $evidenceId
    generated_utc = [DateTime]::UtcNow.ToString("o")
    mode = if ($RecordOnly) { "record_only" } else { "execute" }
    target = [ordered]@{ os = $osName; release = $release }
    host = [ordered]@{
        edition = [string]$os.Caption
        display_version = [string]$os.DisplayVersion
        build = [string]$os.BuildNumber
        architecture = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
        manufacturer = [string]$computer.Manufacturer
        filesystem = [string]$systemDrive.FileSystem
        display_scale_percent = $DisplayScale
        word_version = $wordVersion
    }
    installer = [ordered]@{
        path = $installerItem.FullName
        size = [long]$installerItem.Length
        sha256 = $installerHash
        signature_status = if ([string]$signature.Status -eq "Valid") { "signed" } else { "unsigned" }
        publisher = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
    }
    tests = $testResults
    overall_status = $overall
}
$output = Join-Path $evidenceDirectory "acceptance.json"
$payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $output -Encoding UTF8
[Console]::Out.WriteLine((Resolve-Path -LiteralPath $output).Path)
if ($overall -eq "failed") { exit 1 }
