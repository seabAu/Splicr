[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$OutputDirectory = "",
    [string]$ArchiveDirectory = "",
    [string]$BuildInfoPath = "",
    [string]$SourceInfoPath = "",
    [switch]$KeepWorkDirectory
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LockPath = Join-Path $PSScriptRoot "ffmpeg-source-lock.json"
$ReadmePath = Join-Path $PSScriptRoot "FFMPEG_SOURCE_AUDIT_README.md"
$NoticesPath = Join-Path $PSScriptRoot "THIRD_PARTY_NOTICES.md"
$GraphPath = Join-Path $PSScriptRoot "ffmpeg-source-graph"
$OutputDirectory = if ($OutputDirectory) {
    [IO.Path]::GetFullPath($OutputDirectory)
}
else {
    Join-Path $Root "dist"
}
$BuildInfoPath = if ($BuildInfoPath) {
    [IO.Path]::GetFullPath($BuildInfoPath)
}
else {
    Join-Path $PSScriptRoot "vendor\ffmpeg\BUILD_INFO.txt"
}
$SourceInfoPath = if ($SourceInfoPath) {
    [IO.Path]::GetFullPath($SourceInfoPath)
}
else {
    Join-Path $PSScriptRoot "vendor\ffmpeg\SOURCE_INFO.txt"
}

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7 or newer is required. Run this script with pwsh."
}
if ($Version -notmatch '^\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$') {
    throw "Version must look like 1.2.3 or 1.2.3-rc.1"
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

function Assert-Condition([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw $Message
    }
}

function Copy-Or-DownloadArchive([object]$Archive, [string]$Destination) {
    if ($ArchiveDirectory) {
        $LocalArchive = Join-Path ([IO.Path]::GetFullPath($ArchiveDirectory)) $Archive.filename
        Assert-Condition (Test-Path -LiteralPath $LocalArchive -PathType Leaf) `
            "Missing pinned source archive: $LocalArchive"
        Copy-Item -LiteralPath $LocalArchive -Destination $Destination -Force
    }
    else {
        Invoke-WebRequest -Uri $Archive.url -OutFile $Destination -UseBasicParsing
    }
    $ActualSha256 = Get-Sha256 $Destination
    Assert-Condition ($ActualSha256 -eq $Archive.sha256) `
        "Source archive hash mismatch for $($Archive.name): expected $($Archive.sha256), received $ActualSha256"
}

foreach ($RequiredFile in @($LockPath, $ReadmePath, $NoticesPath, $BuildInfoPath, $SourceInfoPath)) {
    Assert-Condition (Test-Path -LiteralPath $RequiredFile -PathType Leaf) "Missing required file: $RequiredFile"
}
Assert-Condition (Test-Path -LiteralPath $GraphPath -PathType Container) `
    "Missing required source graph: $GraphPath"
& (Join-Path $PSScriptRoot "test-ffmpeg-source-graph.ps1") -GraphDirectory $GraphPath | Out-Null

$Lock = Get-Content -Raw -LiteralPath $LockPath | ConvertFrom-Json
Assert-Condition ($Lock.completeness.corresponding_source_complete -eq $false) `
    "Audit kit must not claim complete corresponding source"
Assert-Condition ($Lock.completeness.public_release_gate_satisfied -eq $false) `
    "Audit kit must not claim the public release gate is satisfied"

$BuildInfo = Get-Content -Raw -LiteralPath $BuildInfoPath
foreach ($Token in @(
    $Lock.binary.reported_version,
    "--enable-shared",
    "--disable-static",
    "--enable-libopenh264",
    "--disable-libx264"
)) {
    Assert-Condition ($BuildInfo.Contains($Token, [StringComparison]::Ordinal)) `
        "BUILD_INFO.txt does not contain required token: $Token"
}
Assert-Condition (-not $BuildInfo.Contains("--enable-gpl", [StringComparison]::Ordinal)) `
    "BUILD_INFO.txt unexpectedly enables GPL"
Assert-Condition (-not $BuildInfo.Contains("--enable-nonfree", [StringComparison]::Ordinal)) `
    "BUILD_INFO.txt unexpectedly enables nonfree components"

$SourceInfo = Get-Content -Raw -LiteralPath $SourceInfoPath
foreach ($Token in @($Lock.binary.release_tag, $Lock.binary.asset, $Lock.binary.sha256)) {
    Assert-Condition ($SourceInfo.Contains($Token, [StringComparison]::Ordinal)) `
        "SOURCE_INFO.txt does not contain required token: $Token"
}

$WorkRoot = Join-Path ([IO.Path]::GetTempPath()) "splicr-ffmpeg-source-audit-$PID"
$KitRoot = Join-Path $WorkRoot "SPLICR-Studio-$Version-FFmpeg-primary-source-audit"
$SourcesRoot = Join-Path $KitRoot "sources"
$OutputZip = Join-Path $OutputDirectory "SPLICR-Studio-$Version-FFmpeg-primary-source-audit.zip"
$OutputChecksum = Join-Path $OutputDirectory "SPLICR-Studio-$Version-FFmpeg-primary-source-audit-SHA256.txt"

try {
    if (Test-Path -LiteralPath $WorkRoot) {
        Remove-Item -LiteralPath $WorkRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $SourcesRoot, $OutputDirectory | Out-Null

    foreach ($Archive in $Lock.primary_source_archives) {
        Copy-Or-DownloadArchive $Archive (Join-Path $SourcesRoot $Archive.filename)
    }
    Copy-Item -LiteralPath $ReadmePath -Destination (Join-Path $KitRoot "README.md")
    Copy-Item -LiteralPath $NoticesPath -Destination (Join-Path $KitRoot "THIRD_PARTY_NOTICES.md")
    Copy-Item -LiteralPath $BuildInfoPath -Destination (Join-Path $KitRoot "BUILD_INFO.txt")
    Copy-Item -LiteralPath $SourceInfoPath -Destination (Join-Path $KitRoot "BINARY_SOURCE_INFO.txt")
    Copy-Item -LiteralPath $GraphPath -Destination (Join-Path $KitRoot "dependency-graph") -Recurse

    $Manifest = [ordered]@{
        schema_version = 1
        package_version = $Version
        generated_at = [DateTimeOffset]::UtcNow.ToString("O")
        status = "audit-only-incomplete-external-dependency-sources"
        binary = $Lock.binary
        primary_source_archives = $Lock.primary_source_archives
        dependency_graph = $Lock.dependency_graph
        completeness = $Lock.completeness
    }
    $Manifest | ConvertTo-Json -Depth 10 | Set-Content `
        -LiteralPath (Join-Path $KitRoot "SOURCE_MANIFEST.json") -Encoding UTF8

    if (Test-Path -LiteralPath $OutputZip) {
        Remove-Item -LiteralPath $OutputZip -Force
    }
    Compress-Archive -LiteralPath $KitRoot -DestinationPath $OutputZip -CompressionLevel Optimal
    "$(Get-Sha256 $OutputZip)  $([IO.Path]::GetFileName($OutputZip))" | Set-Content `
        -LiteralPath $OutputChecksum -Encoding UTF8
    Write-Output $OutputZip
}
finally {
    if (-not $KeepWorkDirectory -and (Test-Path -LiteralPath $WorkRoot)) {
        Remove-Item -LiteralPath $WorkRoot -Recurse -Force
    }
}
