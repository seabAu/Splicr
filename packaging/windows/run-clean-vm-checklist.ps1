[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$ArtifactsDir = (Join-Path $PSScriptRoot "..\..\dist"),
    [string]$PreviousInstaller = "",
    [string]$EvidencePath = "",
    [switch]$ValidateOnly,
    [switch]$ConfirmDisposableMachine
)

$ErrorActionPreference = "Stop"

function Assert-Condition([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw $Message
    }
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-TreeManifest([string]$Root) {
    $Prefix = $Root.TrimEnd([IO.Path]::DirectorySeparatorChar) + `
        [IO.Path]::DirectorySeparatorChar
    return @(
        Get-ChildItem -LiteralPath $Root -File -Recurse |
            Sort-Object -Property FullName |
            ForEach-Object {
                $RelativePath = $_.FullName.Substring($Prefix.Length)
                "$RelativePath|$($_.Length)|$(Get-Sha256 $_.FullName)"
            }
    )
}

function Wait-Condition(
    [scriptblock]$Condition,
    [string]$FailureMessage,
    [int]$TimeoutSeconds = 60
) {
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while (-not (& $Condition) -and [DateTime]::UtcNow -lt $Deadline) {
        Start-Sleep -Milliseconds 250
    }
    Assert-Condition (& $Condition) $FailureMessage
}

function Find-StudioPort {
    foreach ($Port in 8765..8774) {
        try {
            $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1
            $Studio = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/studio/" -TimeoutSec 1
            if (
                $Health.status -eq "ok" -and
                $Studio.Content -match '<title>SPLICR Studio</title>'
            ) {
                return $Port
            }
        }
        catch {
            # A cleanly closed instance and unrelated ports are expected to reject the probe.
        }
    }
    return $null
}

function Confirm-OperatorStep([string]$Id, [string]$Prompt) {
    while ($true) {
        $Answer = (Read-Host "$Prompt [y/n]").Trim().ToLowerInvariant()
        if ($Answer -in @("y", "yes")) {
            $script:OperatorChecks[$Id] = $true
            return
        }
        if ($Answer -in @("n", "no")) {
            $script:OperatorChecks[$Id] = $false
            return
        }
        Write-Host "Please answer y or n."
    }
}

function Install-Candidate([string]$InstallerPath) {
    $Process = Start-Process -FilePath $InstallerPath -ArgumentList @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-"
    ) -Wait -PassThru
    Assert-Condition ($Process.ExitCode -eq 0) `
        "Installer exited with code $($Process.ExitCode)."
}

function Invoke-Checked([string]$FilePath, [string[]]$ArgumentList) {
    $StartInfo = [Diagnostics.ProcessStartInfo]::new()
    $StartInfo.FileName = $FilePath
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    foreach ($Argument in $ArgumentList) {
        $StartInfo.ArgumentList.Add($Argument)
    }
    $Process = [Diagnostics.Process]::new()
    $Process.StartInfo = $StartInfo
    try {
        Assert-Condition ($Process.Start()) "Could not start command: $FilePath"
        $Process.WaitForExit()
        $ExitCode = $Process.ExitCode
    }
    finally {
        $Process.Dispose()
    }
    if ($ExitCode -ne 0) {
        throw "Command failed with exit code ${ExitCode}: $FilePath"
    }
}

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "The clean-VM checklist requires PowerShell 7 or newer (pwsh)."
}
if (-not $IsWindows) {
    throw "The clean-VM checklist must run on Windows."
}
if (-not $ValidateOnly -and -not $ConfirmDisposableMachine) {
    throw "Rerun with -ConfirmDisposableMachine on a disposable clean Windows VM."
}
if ($Version -notmatch '^\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$') {
    throw "Invalid package version: $Version"
}

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
$IsAdministrator = $Principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $ValidateOnly) {
    Assert-Condition (-not $IsAdministrator) `
        "Run this checklist from a standard-user PowerShell session, not an elevated session."
}

$ArtifactsDir = (Resolve-Path -LiteralPath $ArtifactsDir).Path
$InstallerName = "SPLICR-Studio-$Version-Windows-x64-setup.exe"
$PortableName = "SPLICR-Studio-$Version-Windows-x64-portable.zip"
$ChecksumsName = "SPLICR-Studio-$Version-SHA256SUMS.txt"
$Installer = Join-Path $ArtifactsDir $InstallerName
$Portable = Join-Path $ArtifactsDir $PortableName
$Checksums = Join-Path $ArtifactsDir $ChecksumsName
foreach ($RequiredArtifact in @($Installer, $Portable, $Checksums)) {
    Assert-Condition (Test-Path -LiteralPath $RequiredArtifact -PathType Leaf) `
        "Missing package artifact: $RequiredArtifact"
}

$ExpectedHashes = @{}
foreach ($Line in Get-Content -LiteralPath $Checksums) {
    if ($Line -match '^(?<hash>[0-9a-fA-F]{64})\s{2,}(?<file>.+)$') {
        $ExpectedHashes[$Matches.file] = $Matches.hash.ToLowerInvariant()
    }
}
$InstallerSha256 = Get-Sha256 $Installer
$PortableSha256 = Get-Sha256 $Portable
Assert-Condition ($ExpectedHashes[$InstallerName] -eq $InstallerSha256) `
    "Installer SHA-256 does not match $ChecksumsName."
Assert-Condition ($ExpectedHashes[$PortableName] -eq $PortableSha256) `
    "Portable SHA-256 does not match $ChecksumsName."

$PreviousInstallerSha256 = $null
if ($PreviousInstaller) {
    $PreviousInstaller = (Resolve-Path -LiteralPath $PreviousInstaller).Path
    Assert-Condition (Test-Path -LiteralPath $PreviousInstaller -PathType Leaf) `
        "Previous installer is not a file: $PreviousInstaller"
    $PreviousInstallerSha256 = Get-Sha256 $PreviousInstaller
    Assert-Condition ($PreviousInstallerSha256 -ne $InstallerSha256) `
        "PreviousInstaller must identify a different package from the candidate installer."
}
$Scenario = if ($PreviousInstaller) { "upgrade" } else { "fresh" }

if ($ValidateOnly) {
    [ordered]@{
        validation_only = $true
        version = $Version
        installer = [ordered]@{
            file = $InstallerName
            bytes = (Get-Item -LiteralPath $Installer).Length
            sha256 = $InstallerSha256
        }
        portable = [ordered]@{
            file = $PortableName
            bytes = (Get-Item -LiteralPath $Portable).Length
            sha256 = $PortableSha256
        }
        checksums = $ChecksumsName
        scenario = $Scenario
        previous_installer = if ($PreviousInstaller) {
            [ordered]@{
                file = [IO.Path]::GetFileName($PreviousInstaller)
                bytes = (Get-Item -LiteralPath $PreviousInstaller).Length
                sha256 = $PreviousInstallerSha256
            }
        }
        else {
            $null
        }
        passed = $true
    } | ConvertTo-Json -Depth 4
    return
}

if (-not $EvidencePath) {
    $EvidencePath = Join-Path `
        $ArtifactsDir `
        "SPLICR-Studio-$Version-Windows-x64-CLEAN-VM-$($Scenario.ToUpperInvariant())-ACCEPTANCE.json"
}
$EvidencePath = [IO.Path]::GetFullPath($EvidencePath)

$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\SPLICR Studio"
$DataDir = Join-Path $env:LOCALAPPDATA "SPLICR Studio\data"
$StartMenuShortcut = Join-Path `
    ([Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)) `
    "SPLICR Studio.lnk"
$UninstallRegistryPath = `
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{D39B3DFC-EA2E-4BE8-96EC-14D11D67D63C}_is1"

$AutomatedChecks = [ordered]@{
    standard_user = (-not $IsAdministrator)
    clean_install_directory = (-not (Test-Path -LiteralPath $InstallDir))
    clean_data_directory = (-not (Test-Path -LiteralPath $DataDir))
    clean_start_menu = (-not (Test-Path -LiteralPath $StartMenuShortcut))
    clean_uninstall_registration = (-not (Test-Path -LiteralPath $UninstallRegistryPath))
    artifact_checksums = $true
}
foreach ($Property in $AutomatedChecks.GetEnumerator()) {
    Assert-Condition $Property.Value "Clean-VM precondition failed: $($Property.Key)"
}

$script:OperatorChecks = [ordered]@{}
$Failure = $null
$PreviousPort = $null
$FreshPort = $null
$ReinstallPort = $null
$PortablePort = $null
$StartedAt = [DateTime]::UtcNow
$UpgradeEvidence = $null
$ApplicationLicenseSha256 = $null
$RepresentativeStateManifest = Join-Path `
    ([IO.Path]::GetTempPath()) `
    ("SPLICR-upgrade-state-" + [Guid]::NewGuid().ToString("N") + ".json")

try {
    if ($PreviousInstaller) {
        Write-Host "Installing the previous package as the current standard user..."
        Install-Candidate $PreviousInstaller
        Assert-Condition (Test-Path -LiteralPath $InstallDir -PathType Container) `
            "Previous installer did not create $InstallDir."
        Assert-Condition (Test-Path -LiteralPath $StartMenuShortcut -PathType Leaf) `
            "Previous installer did not create the per-user Start-menu shortcut."
        Assert-Condition (Test-Path -LiteralPath $UninstallRegistryPath) `
            "Previous installer did not create the per-user Windows uninstall registration."
        $PreviousExecutable = Join-Path $InstallDir "SPLICR Studio.exe"
        Assert-Condition (Test-Path -LiteralPath $PreviousExecutable -PathType Leaf) `
            "Previous package did not install SPLICR Studio.exe."
        Invoke-Checked $PreviousExecutable @(
            "--package-acceptance-state",
            "seed",
            $RepresentativeStateManifest
        )
        $UpgradeMarker = Join-Path $DataDir "clean-vm-upgrade-marker.txt"
        [IO.File]::WriteAllText(
            $UpgradeMarker,
            "SPLICR clean-VM upgrade must preserve this file.`n"
        )
        $UpgradeMarkerSha256 = Get-Sha256 $UpgradeMarker

        Write-Host "Launching the previous package so its state can be inspected..."
        Start-Process -FilePath $StartMenuShortcut | Out-Null
        Wait-Condition { $null -ne (Find-StudioPort) } `
            "Previous SPLICR package did not expose its health and Studio surfaces."
        $PreviousPort = Find-StudioPort
        $AutomatedChecks.previous_package_served_studio = $true
        Confirm-OperatorStep "previous_package_state_prepared" `
            "Does the previous version show its seeded Library/jobs/profiles/media, and did you prepare any additional resumable work and credential metadata to preserve?"
        Read-Host "Close the previous version's lifecycle window normally, then press Enter"
        Wait-Condition { $null -eq (Find-StudioPort) } `
            "The previous package's private server remained reachable after close."
        $AutomatedChecks.previous_package_window_close_stopped_server = $true
        Write-Host "Installing $InstallerName over the previous package..."
    }
    else {
        Write-Host "Installing $InstallerName as the current standard user..."
    }

    Install-Candidate $Installer
    $AutomatedChecks.install_completed = Test-Path -LiteralPath $InstallDir -PathType Container
    $AutomatedChecks.start_menu_created = `
        Test-Path -LiteralPath $StartMenuShortcut -PathType Leaf
    $AutomatedChecks.uninstall_registration_created = `
        Test-Path -LiteralPath $UninstallRegistryPath
    Assert-Condition $AutomatedChecks.install_completed "Installer did not create $InstallDir."
    Assert-Condition $AutomatedChecks.start_menu_created `
        "Installer did not create the per-user Start-menu shortcut."
    Assert-Condition $AutomatedChecks.uninstall_registration_created `
        "Installer did not create the per-user Windows uninstall registration."
    $InstalledApplicationLicense = Join-Path $InstallDir "LICENSE.txt"
    Assert-Condition (Test-Path -LiteralPath $InstalledApplicationLicense -PathType Leaf) `
        "Candidate installer did not include the application license."
    $ApplicationLicenseSha256 = Get-Sha256 $InstalledApplicationLicense
    $AutomatedChecks.application_license = $true

    if ($PreviousInstaller) {
        $CandidateExecutable = Join-Path $InstallDir "SPLICR Studio.exe"
        Invoke-Checked $CandidateExecutable @(
            "--package-acceptance-state",
            "verify",
            $RepresentativeStateManifest
        )
        $AutomatedChecks.upgrade_reopened_representative_state = $true
        $AutomatedChecks.upgrade_preserved_marker = (
            (Test-Path -LiteralPath $UpgradeMarker -PathType Leaf) -and
            (Get-Sha256 $UpgradeMarker) -eq $UpgradeMarkerSha256
        )
        Assert-Condition $AutomatedChecks.upgrade_preserved_marker `
            "Candidate upgrade changed or removed pre-existing user data."
        $UninstallRegistration = Get-ItemProperty -LiteralPath $UninstallRegistryPath
        $AutomatedChecks.upgrade_registered_candidate_version = `
            ($UninstallRegistration.DisplayVersion -eq $Version)
        Assert-Condition $AutomatedChecks.upgrade_registered_candidate_version `
            "Candidate upgrade did not register version $Version."
        $UpgradeEvidence = [ordered]@{
            file = [IO.Path]::GetFileName($PreviousInstaller)
            bytes = (Get-Item -LiteralPath $PreviousInstaller).Length
            sha256 = $PreviousInstallerSha256
            representative_state_verified = $true
            preservation_marker_sha256 = $UpgradeMarkerSha256
        }
    }

    Write-Host "Launching SPLICR through its Start-menu shortcut..."
    Start-Process -FilePath $StartMenuShortcut | Out-Null
    Wait-Condition { $null -ne (Find-StudioPort) } `
        "SPLICR did not expose its health and Studio surfaces after Start-menu launch."
    $FreshPort = Find-StudioPort
    $AutomatedChecks.start_menu_launch_served_studio = $true

    Confirm-OperatorStep "native_window_visible" `
        "Is the native SPLICR Studio lifecycle window visible and showing a running status?"
    Confirm-OperatorStep "browser_opened_to_studio" `
        "Did the default browser open the complete Studio interface automatically?"
    if ($PreviousInstaller) {
        Confirm-OperatorStep "upgrade_reopened_operator_state" `
            "Did the candidate reopen the previous version's jobs, profiles, settings, credentials metadata, resumable work, and media correctly?"
    }

    Start-Process -FilePath $StartMenuShortcut | Out-Null
    Start-Sleep -Seconds 2
    $AutomatedChecks.second_launch_kept_port = ((Find-StudioPort) -eq $FreshPort)
    Assert-Condition $AutomatedChecks.second_launch_kept_port `
        "The second Start-menu launch did not retain the original Studio service port."
    Confirm-OperatorStep "second_launch_reused_instance" `
        "Did the second Start-menu launch reuse the existing lifecycle window instead of opening another?"
    Confirm-OperatorStep "document_render_playback" `
        "Did document import, a deterministic/configured render, playback, and reopen persistence work?"
    Confirm-OperatorStep "audiogram_and_convert" `
        "Did Audiogram and Convert work without installing or adding FFmpeg to PATH?"

    Start-Process "ms-settings:appsfeatures" | Out-Null
    Confirm-OperatorStep "windows_settings_entry" `
        "Does Windows Settings show one SPLICR Studio entry with the expected version?"

    Read-Host "Close the native lifecycle window normally, then press Enter"
    Wait-Condition { $null -eq (Find-StudioPort) } `
        "The private Studio server remained reachable after the lifecycle window closed."
    $AutomatedChecks.window_close_stopped_server = $true

    Read-Host "Uninstall SPLICR Studio from Windows Settings, then press Enter"
    Wait-Condition { -not (Test-Path -LiteralPath $InstallDir) } `
        "Windows Settings uninstall did not remove the application directory."
    $AutomatedChecks.uninstall_removed_application = $true
    $AutomatedChecks.uninstall_removed_shortcut = `
        -not (Test-Path -LiteralPath $StartMenuShortcut)
    $AutomatedChecks.uninstall_removed_registration = `
        -not (Test-Path -LiteralPath $UninstallRegistryPath)
    $AutomatedChecks.uninstall_preserved_data = `
        Test-Path -LiteralPath $DataDir -PathType Container
    Assert-Condition $AutomatedChecks.uninstall_removed_shortcut `
        "Windows Settings uninstall left the Start-menu shortcut behind."
    Assert-Condition $AutomatedChecks.uninstall_removed_registration `
        "Windows Settings uninstall left its registration behind."
    Assert-Condition $AutomatedChecks.uninstall_preserved_data `
        "Windows Settings uninstall removed the per-user SPLICR data directory."

    Write-Host "Reinstalling the same candidate to verify preserved state..."
    Install-Candidate $Installer
    $AutomatedChecks.reinstall_completed = `
        Test-Path -LiteralPath $InstallDir -PathType Container
    $AutomatedChecks.reinstall_start_menu_created = `
        Test-Path -LiteralPath $StartMenuShortcut -PathType Leaf
    $AutomatedChecks.reinstall_registration_created = `
        Test-Path -LiteralPath $UninstallRegistryPath
    Assert-Condition $AutomatedChecks.reinstall_completed `
        "Reinstall did not recreate $InstallDir."
    Assert-Condition $AutomatedChecks.reinstall_start_menu_created `
        "Reinstall did not recreate the per-user Start-menu shortcut."
    Assert-Condition $AutomatedChecks.reinstall_registration_created `
        "Reinstall did not recreate the per-user Windows uninstall registration."
    Start-Process -FilePath $StartMenuShortcut | Out-Null
    Wait-Condition { $null -ne (Find-StudioPort) } `
        "Reinstalled SPLICR did not expose its health and Studio surfaces."
    $ReinstallPort = Find-StudioPort
    $AutomatedChecks.reinstall_served_studio = $true
    Confirm-OperatorStep "reinstall_reopened_state" `
        "Did the reinstalled app reopen the preserved Library, jobs, profiles, settings, and media?"

    Read-Host "Close the lifecycle window, uninstall the reinstalled app from Windows Settings, then press Enter"
    Wait-Condition { $null -eq (Find-StudioPort) } `
        "The reinstalled Studio server remained reachable after close."
    Wait-Condition { -not (Test-Path -LiteralPath $InstallDir) } `
        "The final Windows Settings uninstall did not remove the application directory."
    $AutomatedChecks.final_uninstall_removed_application = $true
    $AutomatedChecks.final_uninstall_removed_shortcut = `
        -not (Test-Path -LiteralPath $StartMenuShortcut)
    $AutomatedChecks.final_uninstall_removed_registration = `
        -not (Test-Path -LiteralPath $UninstallRegistryPath)
    $AutomatedChecks.final_uninstall_preserved_data = `
        Test-Path -LiteralPath $DataDir -PathType Container
    Assert-Condition $AutomatedChecks.final_uninstall_removed_shortcut `
        "The final Windows Settings uninstall left the Start-menu shortcut behind."
    Assert-Condition $AutomatedChecks.final_uninstall_removed_registration `
        "The final Windows Settings uninstall left its registration behind."
    Assert-Condition $AutomatedChecks.final_uninstall_preserved_data `
        "The final uninstall removed the intentionally preserved data directory."

    $PortableRunRoot = Join-Path `
        ([IO.Path]::GetTempPath()) `
        ("SPLICR Portable Test - resume " + [Guid]::NewGuid().ToString("N"))
    Expand-Archive -LiteralPath $Portable -DestinationPath $PortableRunRoot
    $PortableExecutables = @(
        Get-ChildItem `
            -LiteralPath $PortableRunRoot `
            -Filter "SPLICR Studio.exe" `
            -File `
            -Recurse
    )
    Assert-Condition ($PortableExecutables.Count -eq 1) `
        "Portable archive must contain exactly one SPLICR Studio.exe."
    $PortableAppRoot = $PortableExecutables[0].Directory.FullName
    $PortableApplicationLicense = Join-Path $PortableAppRoot "LICENSE.txt"
    Assert-Condition (Test-Path -LiteralPath $PortableApplicationLicense -PathType Leaf) `
        "Portable candidate did not include the application license."
    Assert-Condition ((Get-Sha256 $PortableApplicationLicense) -eq $ApplicationLicenseSha256) `
        "Portable and installed application licenses do not match."
    $AutomatedChecks.portable_application_license_matches_installer = $true
    $PortableBefore = Get-TreeManifest $PortableAppRoot

    Write-Host "Launching the extracted portable candidate from $PortableRunRoot..."
    Start-Process -FilePath $PortableExecutables[0].FullName | Out-Null
    Wait-Condition { $null -ne (Find-StudioPort) } `
        "Portable SPLICR did not expose its health and Studio surfaces."
    $PortablePort = Find-StudioPort
    $AutomatedChecks.portable_launch_served_studio = $true
    Confirm-OperatorStep "portable_reopened_state" `
        "Did the portable app open the complete Studio and preserved state without installation?"

    Read-Host "Close the portable lifecycle window normally, then press Enter"
    Wait-Condition { $null -eq (Find-StudioPort) } `
        "The portable Studio server remained reachable after close."
    $AutomatedChecks.portable_window_close_stopped_server = $true
    $PortableAfter = Get-TreeManifest $PortableAppRoot
    $PortableChanges = @(
        Compare-Object -ReferenceObject $PortableBefore -DifferenceObject $PortableAfter
    )
    $AutomatedChecks.portable_tree_unchanged = ($PortableChanges.Count -eq 0)
    Assert-Condition $AutomatedChecks.portable_tree_unchanged `
        "The portable application tree changed while SPLICR was running."
}
catch {
    $Failure = $_.Exception.Message
}
finally {
    $AllAutomatedPassed = -not (@(
        $AutomatedChecks.GetEnumerator() | Where-Object { -not $_.Value }
    ).Count)
    $AllOperatorPassed = (
        $script:OperatorChecks.Count -gt 0 -and
        -not (@(
            $script:OperatorChecks.GetEnumerator() | Where-Object { -not $_.Value }
        ).Count)
    )
    $Evidence = [ordered]@{
        schema_version = 2
        version = $Version
        scenario = $Scenario
        started_at_utc = $StartedAt.ToString("o")
        finished_at_utc = [DateTime]::UtcNow.ToString("o")
        operating_system = [Environment]::OSVersion.VersionString
        powershell = $PSVersionTable.PSVersion.ToString()
        elevated = $IsAdministrator
        installer = [ordered]@{
            file = $InstallerName
            bytes = (Get-Item -LiteralPath $Installer).Length
            sha256 = $InstallerSha256
        }
        portable = [ordered]@{
            file = $PortableName
            bytes = (Get-Item -LiteralPath $Portable).Length
            sha256 = $PortableSha256
        }
        observed_ports = [ordered]@{
            previous_package = $PreviousPort
            candidate = $FreshPort
            reinstall = $ReinstallPort
            portable = $PortablePort
        }
        automated_checks = $AutomatedChecks
        operator_checks = $script:OperatorChecks
        previous_package = $UpgradeEvidence
        application_license = [ordered]@{
            identifier = "Apache-2.0"
            sha256 = $ApplicationLicenseSha256
        }
        failure = $Failure
        passed = ($null -eq $Failure -and $AllAutomatedPassed -and $AllOperatorPassed)
    }
    $EvidenceDirectory = Split-Path $EvidencePath -Parent
    if ($EvidenceDirectory) {
        New-Item -ItemType Directory -Force -Path $EvidenceDirectory | Out-Null
    }
    $Evidence | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
    Write-Host "Clean-VM evidence written to $EvidencePath"
}

if ($Failure) {
    throw "Clean-VM checklist failed: $Failure"
}
if (-not $Evidence.passed) {
    throw "Clean-VM checklist recorded one or more failed operator checks."
}
Write-Host "Clean-VM checklist passed."
