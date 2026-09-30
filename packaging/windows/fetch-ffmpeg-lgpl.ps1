[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $PSScriptRoot "vendor\ffmpeg-lgpl"),
    [string]$PackagedLicenseManifest = (Join-Path $PSScriptRoot "ffmpeg-packaged-license-files.tsv"),
    [switch]$ValidateManifestOnly
)

$ErrorActionPreference = "Stop"
$ArchiveName = "ffmpeg-n9.0.2-3-ga5923073bf-win64-lgpl-shared-9.0.zip"
$ReleaseTag = "autobuild-2026-09-24-14-14"
$ExpectedSha256 = "735bae484ba2c3342bfb34df477b9c6b0f43f9819f4d2fde011be293ee1b6517"
$Url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/$ReleaseTag/$ArchiveName"
$Archive = Join-Path $Destination $ArchiveName
$Extracted = Join-Path $Destination ([IO.Path]::GetFileNameWithoutExtension($ArchiveName))

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

$PackagedLicenseRecords = @(Import-Csv -LiteralPath $PackagedLicenseManifest -Delimiter "`t")
foreach ($Record in $PackagedLicenseRecords) {
    if ($Record.package_path -notmatch '^ffmpeg/[A-Za-z0-9._-]+$' -or
        $Record.source_url -notmatch '^https://' -or
        $Record.revision -notmatch '^([0-9a-f]{40}|v[0-9]+(\.[0-9]+){1,3}([._-][0-9A-Za-z]+)*)$' -or
        $Record.sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Invalid packaged FFmpeg license manifest record: $($Record.package_path)"
    }
}
if ($ValidateManifestOnly) {
    Write-Output "Validated $($PackagedLicenseRecords.Count) packaged FFmpeg license manifest records."
    return
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
if (-not (Test-Path -LiteralPath $Archive) -or
    (Get-Sha256 $Archive) -ne $ExpectedSha256) {
    Invoke-WebRequest -Uri $Url -OutFile $Archive -UseBasicParsing
}
$ActualSha256 = Get-Sha256 $Archive
if ($ActualSha256 -ne $ExpectedSha256) {
    throw "Pinned FFmpeg archive hash mismatch: expected $ExpectedSha256, received $ActualSha256"
}

if (Test-Path -LiteralPath $Extracted) {
    Remove-Item -LiteralPath $Extracted -Recurse -Force
}
Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
$Bin = Join-Path $Extracted "bin"
foreach ($Tool in @("ffmpeg.exe", "ffprobe.exe")) {
    if (-not (Test-Path -LiteralPath (Join-Path $Bin $Tool))) {
        throw "Pinned FFmpeg archive is missing $Tool"
    }
}
foreach ($Record in $PackagedLicenseRecords) {
    $LicenseName = Split-Path $Record.package_path -Leaf
    $LicensePath = Join-Path $Extracted $LicenseName
    Invoke-WebRequest -Uri $Record.source_url -OutFile $LicensePath -UseBasicParsing
    $ActualLicenseSha256 = Get-Sha256 $LicensePath
    if ($ActualLicenseSha256 -ne $Record.sha256) {
        throw "Pinned license hash mismatch for $($Record.package_path): expected $($Record.sha256), received $ActualLicenseSha256"
    }
}
@(
    "Provider: BtbN/FFmpeg-Builds"
    "Release tag: $ReleaseTag"
    "Asset: $ArchiveName"
    "Asset URL: $Url"
    "SHA-256: $ExpectedSha256"
    "Variant: Windows x64 LGPL shared"
    ""
    "Additional packaged dependency licenses:"
    $PackagedLicenseRecords | ForEach-Object {
        "$($_.package_path) | revision $($_.revision) | SHA-256 $($_.sha256) | $($_.source_url)"
    }
) | Set-Content -LiteralPath (Join-Path $Extracted "SOURCE_INFO.txt") -Encoding UTF8

Write-Output $Bin
