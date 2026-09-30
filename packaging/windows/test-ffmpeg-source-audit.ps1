[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$ArchivePath = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LockPath = Join-Path $PSScriptRoot "ffmpeg-source-lock.json"
$ArchivePath = if ($ArchivePath) {
    [IO.Path]::GetFullPath($ArchivePath)
}
else {
    Join-Path $Root "dist\SPLICR-Studio-$Version-FFmpeg-primary-source-audit.zip"
}
$ChecksumPath = Join-Path (Split-Path $ArchivePath -Parent) `
    "SPLICR-Studio-$Version-FFmpeg-primary-source-audit-SHA256.txt"

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7 or newer is required. Run this script with pwsh."
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

Assert-Condition (Test-Path -LiteralPath $ArchivePath -PathType Leaf) "Audit archive not found: $ArchivePath"
Assert-Condition (Test-Path -LiteralPath $ChecksumPath -PathType Leaf) `
    "Audit archive checksum not found: $ChecksumPath"
$ChecksumLine = @(Get-Content -LiteralPath $ChecksumPath | Where-Object { $_.Trim() })[0]
$ChecksumParts = $ChecksumLine -split '\s+', 2
Assert-Condition ($ChecksumParts.Count -eq 2) "Audit checksum file is malformed"
Assert-Condition ($ChecksumParts[0] -eq (Get-Sha256 $ArchivePath)) "Audit archive checksum mismatch"
Assert-Condition ($ChecksumParts[1].Trim() -eq [IO.Path]::GetFileName($ArchivePath)) `
    "Audit checksum filename does not match the archive"
$Lock = Get-Content -Raw -LiteralPath $LockPath | ConvertFrom-Json
$WorkRoot = Join-Path ([IO.Path]::GetTempPath()) "splicr-ffmpeg-source-audit-test-$PID"

try {
    New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null
    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $WorkRoot -Force
    $KitRoot = Join-Path $WorkRoot "SPLICR-Studio-$Version-FFmpeg-primary-source-audit"
    foreach ($RelativePath in @(
        "README.md",
        "THIRD_PARTY_NOTICES.md",
        "BUILD_INFO.txt",
        "BINARY_SOURCE_INFO.txt",
        "SOURCE_MANIFEST.json"
    )) {
        Assert-Condition (Test-Path -LiteralPath (Join-Path $KitRoot $RelativePath) -PathType Leaf) `
            "Audit archive is missing $RelativePath"
    }

    $Manifest = Get-Content -Raw -LiteralPath (Join-Path $KitRoot "SOURCE_MANIFEST.json") | ConvertFrom-Json
    Assert-Condition ($Manifest.status -eq "audit-only-incomplete-external-dependency-sources") `
        "Audit archive has an unexpected status"
    Assert-Condition ($Manifest.completeness.corresponding_source_complete -eq $false) `
        "Audit archive must not claim complete corresponding source"
    Assert-Condition ($Manifest.completeness.public_release_gate_satisfied -eq $false) `
        "Audit archive must not claim the public release gate is satisfied"

    foreach ($Archive in $Lock.primary_source_archives) {
        $SourcePath = Join-Path $KitRoot "sources\$($Archive.filename)"
        Assert-Condition (Test-Path -LiteralPath $SourcePath -PathType Leaf) `
            "Audit archive is missing $($Archive.filename)"
        Assert-Condition ((Get-Sha256 $SourcePath) -eq $Archive.sha256) `
            "Audit archive hash mismatch for $($Archive.filename)"
    }
    Write-Output "FFmpeg primary-source audit kit passed. Public corresponding-source gate remains open."
}
finally {
    if (Test-Path -LiteralPath $WorkRoot) {
        Remove-Item -LiteralPath $WorkRoot -Recurse -Force
    }
}
