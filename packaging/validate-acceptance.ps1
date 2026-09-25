[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $AcceptanceRoot,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string] $InstallerHash
)

$ErrorActionPreference = "Stop"
$requiredFunctionalGates = @(
    "silent_clean_install", "responsive_launch", "all_input_families", "save_and_recover",
    "mixed_script_50_recipient_batch", "unicode_and_long_paths", "locked_file_recovery",
    "upgrade_from_2_1_1", "silent_uninstall"
)
$requiredScales = @(100, 150, 200)
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
    $verifiedScales = @()
    $evidenceIds = @()
    foreach ($item in $evidence) {
        if ([int]$item.schema_version -ne 1 -or [string]$item.mode -ne "execute") { continue }
        if ([string]$item.target.os -ne $target.os -or [string]$item.target.release -ne $target.release) { continue }
        if ([string]$item.host.os -ne $target.os -or [string]$item.host.display_version -ne $target.release) { continue }
        if ([string]$item.host.architecture -ne "x64" -or [string]$item.host.build -notmatch '^\d{5}$') { continue }
        if ([string]$item.host.display_scale_measurement -ne "GetDpiForSystem") { continue }
        if ([string]$item.installer.sha256 -ne $InstallerHash.ToLowerInvariant()) { continue }
        if ([string]$item.overall_status -ne "passed") { continue }

        $gateMap = @{}
        $duplicateGate = $false
        foreach ($gate in @($item.tests)) {
            $id = [string]$gate.id
            if ($gateMap.ContainsKey($id)) { $duplicateGate = $true; break }
            $gateMap[$id] = [string]$gate.status
        }
        if ($duplicateGate) { continue }
        $functionalPassed = $true
        foreach ($id in $requiredFunctionalGates) {
            if (-not $gateMap.ContainsKey($id) -or $gateMap[$id] -ne "passed") { $functionalPassed = $false; break }
        }
        if (-not $functionalPassed) { continue }
        $scale = [int]$item.host.display_scale_percent
        if ($scale -notin $requiredScales) { continue }
        if (-not $gateMap.ContainsKey("display_scale_$scale") -or $gateMap["display_scale_$scale"] -ne "passed") { continue }
        $verifiedScales += $scale
        $evidenceIds += [string]$item.evidence_id
    }
    $verifiedScales = @($verifiedScales | Sort-Object -Unique)
    $complete = @($requiredScales | Where-Object { $_ -notin $verifiedScales }).Count -eq 0
    $target.state = if ($complete) { "verified" } else { "machine_verification_pending" }
    $target.verified_scales = $verifiedScales
    $target.evidence = @($evidenceIds | Sort-Object -Unique)
}

Write-Output ($targets | ConvertTo-Json -Depth 6)
