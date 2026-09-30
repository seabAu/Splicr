[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$')]
    [string]$Version,
    [string]$ArtifactsDir = (Join-Path $PSScriptRoot "..\..\dist"),
    [string]$PreviousInstaller = "",
    [string]$WorkRoot = (Join-Path ([IO.Path]::GetTempPath()) "splicr-package-acceptance"),
    [string]$EvidencePath = "",
    [switch]$KeepWorkRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "Package acceptance requires PowerShell 7 or newer (pwsh)."
}

function Assert-Condition([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw $Message
    }
}

function Get-Sha256([string]$Path) {
    $Stream = [IO.File]::OpenRead($Path)
    try {
        $Hasher = [Security.Cryptography.SHA256]::Create()
        try {
            return ([BitConverter]::ToString($Hasher.ComputeHash($Stream))).Replace("-", "").ToLowerInvariant()
        }
        finally {
            $Hasher.Dispose()
        }
    }
    finally {
        $Stream.Dispose()
    }
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

function Invoke-Captured([string]$FilePath, [string[]]$ArgumentList) {
    $Output = (& $FilePath @ArgumentList 2>&1 | Out-String)
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw "Command failed with exit code ${ExitCode}: $FilePath`n$Output"
    }
    return $Output
}

function Get-TreeManifest([string]$Root, [switch]$ExcludeUninstaller) {
    $Prefix = $Root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    return @(
        Get-ChildItem -LiteralPath $Root -File -Recurse |
            Sort-Object -Property FullName |
            ForEach-Object {
                $RelativePath = $_.FullName.Substring($Prefix.Length)
                if (-not $ExcludeUninstaller -or $RelativePath -notmatch '^unins\d+\.(dat|exe|msg)$') {
                    "$RelativePath|$($_.Length)|$(Get-Sha256 $_.FullName)"
                }
            }
    )
}

function Wait-PathRemoved([string]$Path, [int]$TimeoutSeconds = 30) {
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ((Test-Path -LiteralPath $Path) -and [DateTime]::UtcNow -lt $Deadline) {
        Start-Sleep -Milliseconds 200
    }
    Assert-Condition (-not (Test-Path -LiteralPath $Path)) "Timed out waiting for removal: $Path"
}

function Stop-ProcessesUnder([string]$Root) {
    $Prefix = $Root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    foreach ($Process in Get-Process -ErrorAction SilentlyContinue) {
        try {
            if ($Process.Path -and $Process.Path.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)) {
                Stop-Process -Id $Process.Id -Force -ErrorAction Stop
            }
        }
        catch {
            # System processes and processes that exit during enumeration may not expose Path.
        }
    }
}

$ArtifactsDir = (Resolve-Path -LiteralPath $ArtifactsDir).Path
$PortableName = "SPLICR-Studio-$Version-Windows-x64-portable.zip"
$InstallerName = "SPLICR-Studio-$Version-Windows-x64-setup.exe"
$ChecksumsName = "SPLICR-Studio-$Version-SHA256SUMS.txt"
$PortableZip = Join-Path $ArtifactsDir $PortableName
$Installer = Join-Path $ArtifactsDir $InstallerName
$Checksums = Join-Path $ArtifactsDir $ChecksumsName
$PackagedLicenseManifest = Join-Path $PSScriptRoot "ffmpeg-packaged-license-files.tsv"
$PackagedLicenseRecords = @(Import-Csv -LiteralPath $PackagedLicenseManifest -Delimiter "`t")

foreach ($RequiredArtifact in @($PortableZip, $Installer, $Checksums)) {
    Assert-Condition (Test-Path -LiteralPath $RequiredArtifact -PathType Leaf) `
        "Missing package artifact: $RequiredArtifact"
}

$ExpectedHashes = @{}
foreach ($Line in Get-Content -LiteralPath $Checksums) {
    if ($Line -match '^(?<hash>[0-9a-fA-F]{64})\s{2,}(?<file>.+)$') {
        $ExpectedHashes[$Matches.file] = $Matches.hash.ToLowerInvariant()
    }
}
foreach ($ArtifactName in @($PortableName, $InstallerName)) {
    Assert-Condition ($ExpectedHashes.ContainsKey($ArtifactName)) `
        "Checksum manifest does not contain $ArtifactName"
}

$PortableSha256 = Get-Sha256 $PortableZip
$InstallerSha256 = Get-Sha256 $Installer
Assert-Condition ($PortableSha256 -eq $ExpectedHashes[$PortableName]) `
    "Portable archive SHA-256 does not match $ChecksumsName"
Assert-Condition ($InstallerSha256 -eq $ExpectedHashes[$InstallerName]) `
    "Installer SHA-256 does not match $ChecksumsName"

$WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
$WorkRootRoot = [IO.Path]::GetPathRoot($WorkRoot)
Assert-Condition ($WorkRoot -ne $WorkRootRoot) "WorkRoot cannot be a filesystem root"
New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null
$RunRoot = Join-Path $WorkRoot ("run-" + [Guid]::NewGuid().ToString("N"))
$RunRoot = [IO.Path]::GetFullPath($RunRoot)
$WorkPrefix = $WorkRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
Assert-Condition ($RunRoot.StartsWith($WorkPrefix, [StringComparison]::OrdinalIgnoreCase)) `
    "Acceptance run directory escaped WorkRoot"
New-Item -ItemType Directory -Path $RunRoot | Out-Null

if (-not $EvidencePath) {
    $EvidencePath = Join-Path $ArtifactsDir "SPLICR-Studio-$Version-Windows-x64-ACCEPTANCE.json"
}
$EvidencePath = [IO.Path]::GetFullPath($EvidencePath)
$OriginalLocalAppData = $env:LOCALAPPDATA
$InstallDir = Join-Path $RunRoot "installed"
$Installed = $false

try {
    $PortableRoot = Join-Path $RunRoot "Portable Test – résumé"
    Expand-Archive -LiteralPath $PortableZip -DestinationPath $PortableRoot
    $PortableExecutables = @(Get-ChildItem -LiteralPath $PortableRoot -Filter "SPLICR Studio.exe" -File -Recurse)
    Assert-Condition ($PortableExecutables.Count -eq 1) `
        "Portable archive must contain exactly one SPLICR Studio.exe"
    $PortableAppRoot = $PortableExecutables[0].Directory.FullName
    $PortableBefore = Get-TreeManifest $PortableAppRoot
    $PortableLocalAppData = Join-Path $RunRoot "portable-localappdata"
    New-Item -ItemType Directory -Path $PortableLocalAppData | Out-Null
    $env:LOCALAPPDATA = $PortableLocalAppData
    Invoke-Checked $PortableExecutables[0].FullName @("--package-smoke-test")
    $PortableAfter = Get-TreeManifest $PortableAppRoot
    $PortableChanges = @(Compare-Object -ReferenceObject $PortableBefore -DifferenceObject $PortableAfter)
    Assert-Condition ($PortableChanges.Count -eq 0) `
        "Portable package files changed during package smoke"
    $PortableDataDir = Join-Path $PortableLocalAppData "SPLICR Studio\data"
    Assert-Condition (Test-Path -LiteralPath $PortableDataDir -PathType Container) `
        "Portable package did not create state under redirected per-user data"

    $InstalledLocalAppData = Join-Path $RunRoot "installed-localappdata"
    New-Item -ItemType Directory -Path $InstalledLocalAppData | Out-Null
    $env:LOCALAPPDATA = $InstalledLocalAppData
    $UpgradeEvidence = $null
    $UpgradeMarker = $null
    $UpgradeMarkerSha256 = $null
    if ($PreviousInstaller) {
        $PreviousInstaller = (Resolve-Path -LiteralPath $PreviousInstaller).Path
        $PreviousInstallerSha256 = Get-Sha256 $PreviousInstaller
        $PreviousInstallLog = Join-Path $RunRoot "previous-install.log"
        Invoke-Checked $PreviousInstaller @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            "/DIR=$InstallDir",
            "/LOG=$PreviousInstallLog"
        )
        $Installed = $true
        $PreviousExecutable = Join-Path $InstallDir "SPLICR Studio.exe"
        Assert-Condition (Test-Path -LiteralPath $PreviousExecutable -PathType Leaf) `
            "Previous installer did not install SPLICR Studio.exe"
        Invoke-Checked $PreviousExecutable @("--package-smoke-test")
        $PreviousDataDir = Join-Path $InstalledLocalAppData "SPLICR Studio\data"
        Assert-Condition (Test-Path -LiteralPath $PreviousDataDir -PathType Container) `
            "Previous package did not create redirected per-user data"
        $UpgradeMarker = Join-Path $PreviousDataDir "upgrade-preservation-marker.txt"
        [IO.File]::WriteAllText($UpgradeMarker, "SPLICR upgrade must preserve this file.`n")
        $UpgradeMarkerSha256 = Get-Sha256 $UpgradeMarker
        $UpgradeEvidence = [ordered]@{
            file = [IO.Path]::GetFileName($PreviousInstaller)
            sha256 = $PreviousInstallerSha256
            package_smoke = $true
        }
    }

    $InstallLog = Join-Path $RunRoot "install.log"
    Invoke-Checked $Installer @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        "/DIR=$InstallDir",
        "/LOG=$InstallLog"
    )
    $Installed = $true

    $InstalledExecutable = Join-Path $InstallDir "SPLICR Studio.exe"
    $InternalDir = Join-Path $InstallDir "_internal"
    $FfmpegDir = Join-Path $InternalDir "ffmpeg"
    foreach ($RequiredPayload in @(
        $InstalledExecutable,
        (Join-Path $InternalDir "BUILD_INFO.txt"),
        (Join-Path $InternalDir "THIRD_PARTY_NOTICES.md"),
        (Join-Path $FfmpegDir "ffmpeg.exe"),
        (Join-Path $FfmpegDir "ffprobe.exe"),
        (Join-Path $FfmpegDir "LICENSE.txt"),
        (Join-Path $FfmpegDir "SOURCE_INFO.txt")
    )) {
        Assert-Condition (Test-Path -LiteralPath $RequiredPayload -PathType Leaf) `
            "Installed package is missing: $RequiredPayload"
    }
    $ValidatedDependencyLicenses = @()
    foreach ($Record in $PackagedLicenseRecords) {
        Assert-Condition ($Record.package_path -match '^ffmpeg/[A-Za-z0-9._-]+$') `
            "Invalid packaged FFmpeg license path: $($Record.package_path)"
        Assert-Condition ($Record.sha256 -match '^[0-9a-f]{64}$') `
            "Invalid packaged FFmpeg license SHA-256: $($Record.package_path)"
        $LicensePath = Join-Path $InternalDir ($Record.package_path -replace '/', '\\')
        Assert-Condition (Test-Path -LiteralPath $LicensePath -PathType Leaf) `
            "Installed package is missing dependency license: $($Record.package_path)"
        Assert-Condition ((Get-Sha256 $LicensePath) -eq $Record.sha256) `
            "Installed dependency license hash differs from its pinned source: $($Record.package_path)"
        $ValidatedDependencyLicenses += [ordered]@{
            file = $Record.package_path
            revision = $Record.revision
            sha256 = $Record.sha256
        }
    }
    $FfmpegDlls = @(Get-ChildItem -LiteralPath $FfmpegDir -Filter "*.dll" -File)
    Assert-Condition ($FfmpegDlls.Count -ge 5) "Installed FFmpeg shared-library payload is incomplete"
    $InstalledPayload = Get-TreeManifest $InstallDir -ExcludeUninstaller
    $InstalledPayloadChanges = @(
        Compare-Object -ReferenceObject $PortableBefore -DifferenceObject $InstalledPayload
    )
    Assert-Condition ($InstalledPayloadChanges.Count -eq 0) `
        "Installed application payload does not exactly match the portable package"

    $Ffmpeg = Join-Path $FfmpegDir "ffmpeg.exe"
    $Ffprobe = Join-Path $FfmpegDir "ffprobe.exe"
    $FfmpegVersion = Invoke-Captured $Ffmpeg @("-version")
    Assert-Condition ($FfmpegVersion -match '--enable-shared') "Bundled FFmpeg is not a shared build"
    Assert-Condition ($FfmpegVersion -match '--disable-static') "Bundled FFmpeg did not disable static libraries"
    Assert-Condition ($FfmpegVersion -match '--disable-libx264') "Bundled FFmpeg did not disable libx264"
    Assert-Condition ($FfmpegVersion -notmatch '--enable-gpl') "Bundled FFmpeg unexpectedly enables GPL components"
    Assert-Condition ($FfmpegVersion -notmatch '--enable-nonfree') "Bundled FFmpeg unexpectedly enables nonfree components"
    $EncoderListing = Invoke-Captured $Ffmpeg @("-hide_banner", "-encoders")
    Assert-Condition ($EncoderListing -match '(?m)^\s*V\S*\s+libopenh264\b') `
        "Bundled FFmpeg does not expose libopenh264"
    Assert-Condition ($EncoderListing -notmatch '(?m)^\s*V\S*\s+libx264\b') `
        "Bundled FFmpeg unexpectedly exposes libx264"

    Invoke-Checked $InstalledExecutable @("--package-smoke-test")
    $InstalledDataDir = Join-Path $InstalledLocalAppData "SPLICR Studio\data"
    Assert-Condition (Test-Path -LiteralPath $InstalledDataDir -PathType Container) `
        "Installed package did not create redirected per-user data"
    if ($UpgradeMarker) {
        Assert-Condition (Test-Path -LiteralPath $UpgradeMarker -PathType Leaf) `
            "Upgrade removed pre-existing user data"
        Assert-Condition ((Get-Sha256 $UpgradeMarker) -eq $UpgradeMarkerSha256) `
            "Upgrade changed pre-existing user data"
        $UpgradeEvidence.user_data_preserved = $true
    }
    $PreservationMarker = Join-Path $InstalledDataDir "uninstall-preservation-marker.txt"
    [IO.File]::WriteAllText($PreservationMarker, "SPLICR uninstall must preserve this file.`n")

    $RenderedMp4 = Join-Path $RunRoot "installed-openh264.mp4"
    Invoke-Checked $Ffmpeg @(
        "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=navy:s=320x240:r=24:d=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libopenh264", "-rc_mode", "bitrate", "-b:v", "500k",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-y", $RenderedMp4
    )
    $ProbeJson = Invoke-Captured $Ffprobe @(
        "-v", "error",
        "-show_entries", "stream=codec_name,codec_type,pix_fmt",
        "-show_entries", "format=duration,format_name",
        "-of", "json",
        $RenderedMp4
    )
    $Probe = $ProbeJson | ConvertFrom-Json
    $VideoStreams = @($Probe.streams | Where-Object { $_.codec_type -eq "video" })
    $AudioStreams = @($Probe.streams | Where-Object { $_.codec_type -eq "audio" })
    Assert-Condition ($VideoStreams.Count -eq 1) "Acceptance MP4 does not contain one video stream"
    Assert-Condition ($AudioStreams.Count -eq 1) "Acceptance MP4 does not contain one audio stream"
    Assert-Condition ($VideoStreams[0].codec_name -eq "h264") "Acceptance MP4 video is not H.264"
    Assert-Condition ($VideoStreams[0].pix_fmt -eq "yuv420p") "Acceptance MP4 pixel format is not yuv420p"
    Assert-Condition ($AudioStreams[0].codec_name -eq "aac") "Acceptance MP4 audio is not AAC"
    $Duration = [double]::Parse($Probe.format.duration, [Globalization.CultureInfo]::InvariantCulture)
    Assert-Condition ($Duration -ge 0.9 -and $Duration -le 1.1) `
        "Acceptance MP4 duration is outside tolerance: $Duration"

    $Uninstaller = Join-Path $InstallDir "unins000.exe"
    Assert-Condition (Test-Path -LiteralPath $Uninstaller -PathType Leaf) `
        "Installed package does not contain its uninstaller"
    Invoke-Checked $Uninstaller @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
    $Installed = $false
    Wait-PathRemoved $InstallDir
    Assert-Condition (Test-Path -LiteralPath $PreservationMarker -PathType Leaf) `
        "Uninstall removed per-user data"

    $SourceInfo = Get-Content -LiteralPath (Join-Path $PortableAppRoot "_internal\ffmpeg\SOURCE_INFO.txt")
    $SourceShaLine = $SourceInfo | Where-Object { $_ -like "SHA-256:*" } | Select-Object -First 1
    Assert-Condition ([bool]$SourceShaLine) "Bundled FFmpeg source record does not contain SHA-256"
    $FfmpegFirstLine = ($FfmpegVersion -split "`r?`n")[0]
    $Checks = [ordered]@{
        checksum_manifest = $true
        portable_package_smoke = $true
        portable_tree_unchanged = $true
        portable_per_user_data = $true
        installed_payload_matches_portable = $true
        installed_package_smoke = $true
        lgpl_shared_configuration = $true
        dependency_license_files = $true
        openh264_h264_aac_mp4 = $true
        uninstall_removed_application = $true
        uninstall_preserved_user_data = $true
    }
    if ($UpgradeEvidence) {
        $Checks.upgrade_package_smoke = $true
        $Checks.upgrade_preserved_user_data = $true
    }
    $Evidence = [ordered]@{
        schema_version = 1
        version = $Version
        tested_at_utc = [DateTime]::UtcNow.ToString("o")
        operating_system = [Environment]::OSVersion.VersionString
        portable = [ordered]@{
            file = $PortableName
            bytes = (Get-Item -LiteralPath $PortableZip).Length
            sha256 = $PortableSha256
        }
        installer = [ordered]@{
            file = $InstallerName
            bytes = (Get-Item -LiteralPath $Installer).Length
            sha256 = $InstallerSha256
        }
        media_tools = [ordered]@{
            ffmpeg = $FfmpegFirstLine
            source_sha256 = $SourceShaLine.Substring("SHA-256:".Length).Trim()
            shared_dll_count = $FfmpegDlls.Count
            dependency_licenses = $ValidatedDependencyLicenses
        }
        upgrade = $UpgradeEvidence
        checks = $Checks
    }
    $EvidenceDirectory = Split-Path $EvidencePath -Parent
    if ($EvidenceDirectory) {
        New-Item -ItemType Directory -Force -Path $EvidenceDirectory | Out-Null
    }
    $Evidence | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
    Write-Output "Package acceptance passed: $EvidencePath"
}
finally {
    $env:LOCALAPPDATA = $OriginalLocalAppData
    if ($Installed) {
        $Uninstaller = Join-Path $InstallDir "unins000.exe"
        if (Test-Path -LiteralPath $Uninstaller -PathType Leaf) {
            try {
                Invoke-Checked $Uninstaller @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
                Wait-PathRemoved $InstallDir
            }
            catch {
                Write-Warning "Acceptance cleanup could not uninstall SPLICR Studio: $_"
            }
        }
    }
    if (-not $KeepWorkRoot -and (Test-Path -LiteralPath $RunRoot)) {
        Stop-ProcessesUnder $RunRoot
        Remove-Item -LiteralPath $RunRoot -Recurse -Force
    }
}
