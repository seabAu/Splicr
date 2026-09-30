[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $PSScriptRoot "vendor\ffmpeg-lgpl")
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
@(
    "Provider: BtbN/FFmpeg-Builds"
    "Release tag: $ReleaseTag"
    "Asset: $ArchiveName"
    "Asset URL: $Url"
    "SHA-256: $ExpectedSha256"
    "Variant: Windows x64 LGPL shared"
) | Set-Content -LiteralPath (Join-Path $Extracted "SOURCE_INFO.txt") -Encoding UTF8

Write-Output $Bin
