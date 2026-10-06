[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BundleDirectory
)

$ErrorActionPreference = "Stop"
$BundleDirectory = [IO.Path]::GetFullPath($BundleDirectory)

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7 or newer is required. Run this script with pwsh."
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

function Assert-SafeRelativePath([string]$RelativePath) {
    Assert-Condition (-not [IO.Path]::IsPathRooted($RelativePath)) "Rooted path is forbidden: $RelativePath"
    $Segments = $RelativePath.Replace("\", "/").Split("/", [StringSplitOptions]::RemoveEmptyEntries)
    Assert-Condition ($Segments.Count -gt 0 -and -not ($Segments -contains "..")) `
        "Unsafe relative path: $RelativePath"
}

Assert-Condition (Test-Path -LiteralPath $BundleDirectory -PathType Container) `
    "Corresponding-source bundle not found: $BundleDirectory"
foreach ($RelativePath in @(
    "README.md",
    "SOURCE_MANIFEST.json",
    "SOURCE-SHA256SUMS.txt",
    "dependency-sources/COLLECTION_INFO.txt",
    "dependency-sources/collection-manifest.tsv",
    "dependency-sources/license-candidate-inventory.tsv",
    "primary-sources/ffmpeg-source.zip",
    "primary-sources/openh264-source.zip",
    "primary-sources/btbn-build-scripts.zip",
    "tooling/ffmpeg-source-license-review.tsv",
    "tooling/THIRD_PARTY_NOTICES.md",
    "tooling/ffmpeg-correspondence-evidence.json",
    "build-evidence/Dockerfile.offline.prepared",
    "build-evidence/podman-offline-dependencies.log",
    "build-evidence/ffmpeg-offline-binary.log"
)) {
    Assert-Condition (Test-Path -LiteralPath (Join-Path $BundleDirectory $RelativePath) -PathType Leaf) `
        "Corresponding-source bundle is missing $RelativePath"
}

$Manifest = Get-Content -Raw -LiteralPath (Join-Path $BundleDirectory "SOURCE_MANIFEST.json") | ConvertFrom-Json
Assert-Condition ($Manifest.status -eq "corresponding-source-complete-publication-pending") `
    "Unexpected corresponding-source status"
Assert-Condition ($Manifest.completeness.all_enabled_external_dependency_sources_included -eq $true) `
    "Bundle does not claim the complete enabled dependency source graph"
Assert-Condition ($Manifest.completeness.license_and_notice_review_complete -eq $true) `
    "Bundle does not claim completed license/notice review"
Assert-Condition ($Manifest.completeness.correspondence_rebuild_verified -eq $true) `
    "Bundle does not claim a verified correspondence rebuild"
Assert-Condition ($Manifest.completeness.corresponding_source_complete -eq $true) `
    "Bundle does not claim complete corresponding source"
Assert-Condition ($Manifest.completeness.public_release_gate_satisfied -eq $false) `
    "An unpublished candidate must not claim the public release gate is satisfied"
Assert-Condition ($Manifest.collection.enabled_stage_count -eq 90) "Unexpected stage count"
Assert-Condition ($Manifest.collection.source_bearing_stage_count -eq 85) "Unexpected source archive count"
Assert-Condition ($Manifest.collection.source_locator_count -eq 92) "Unexpected source locator count"
Assert-Condition ($Manifest.collection.reviewed_candidate_count -eq 1684) "Unexpected reviewed candidate count"

$ChecksumPath = Join-Path $BundleDirectory "SOURCE-SHA256SUMS.txt"
$ExpectedPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($Line in @(Get-Content -LiteralPath $ChecksumPath | Where-Object { $_.Trim() })) {
    $Parts = $Line -split '\s+', 2
    Assert-Condition ($Parts.Count -eq 2 -and $Parts[0] -match '^[0-9a-f]{64}$') `
        "Malformed bundle checksum line: $Line"
    $RelativePath = $Parts[1].Trim().Replace("\", "/")
    Assert-SafeRelativePath $RelativePath
    Assert-Condition ($ExpectedPaths.Add($RelativePath)) "Duplicate bundle checksum path: $RelativePath"
    $Path = Join-Path $BundleDirectory $RelativePath
    Assert-Condition (Test-Path -LiteralPath $Path -PathType Leaf) "Bundle checksum target is missing: $RelativePath"
    Assert-Condition ((Get-Sha256 $Path) -eq $Parts[0]) "Bundle checksum mismatch: $RelativePath"
}

$ActualPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($File in Get-ChildItem -LiteralPath $BundleDirectory -File -Recurse) {
    $RelativePath = [IO.Path]::GetRelativePath($BundleDirectory, $File.FullName).Replace("\", "/")
    if ($RelativePath -ne "SOURCE-SHA256SUMS.txt") {
        [void]$ActualPaths.Add($RelativePath)
    }
}
Assert-Condition ($ExpectedPaths.SetEquals($ActualPaths)) `
    "Bundle checksum manifest does not cover exactly every non-manifest file"

$CollectionRows = @(Import-Csv -LiteralPath `
    (Join-Path $BundleDirectory "dependency-sources/collection-manifest.tsv") -Delimiter "`t")
$CollectedRows = @($CollectionRows | Where-Object { $_.source_status -eq "collected" })
Assert-Condition ($CollectionRows.Count -eq 90 -and $CollectedRows.Count -eq 85) `
    "Bundled collection manifest is incomplete"
foreach ($Row in $CollectedRows) {
    Assert-SafeRelativePath $Row.archive_name
    $ArchivePath = Join-Path $BundleDirectory "dependency-sources/stages/$($Row.archive_name)"
    Assert-Condition (Test-Path -LiteralPath $ArchivePath -PathType Leaf) `
        "Bundled source archive is missing: $($Row.archive_name)"
    Assert-Condition ((Get-Sha256 $ArchivePath) -eq $Row.archive_sha256) `
        "Bundled source archive hash mismatch: $($Row.archive_name)"
}

foreach ($Archive in $Manifest.primary_source_archives) {
    $Path = Join-Path $BundleDirectory "primary-sources/$($Archive.filename)"
    Assert-Condition ((Get-Sha256 $Path) -eq $Archive.sha256) `
        "Bundled primary source hash mismatch: $($Archive.filename)"
}

$Evidence = $Manifest.correspondence_evidence
foreach ($File in $Evidence.files | Where-Object { $_.include_in_source_bundle }) {
    $Path = Join-Path $BundleDirectory "build-evidence/$([IO.Path]::GetFileName($File.relative_path))"
    Assert-Condition ((Get-Item -LiteralPath $Path).Length -eq $File.size_bytes) `
        "Bundled build-evidence size mismatch: $($File.relative_path)"
    Assert-Condition ((Get-Sha256 $Path) -eq $File.sha256) `
        "Bundled build-evidence hash mismatch: $($File.relative_path)"
}
foreach ($Patch in $Evidence.patches) {
    $RelativePath = if ($Patch.relative_path.StartsWith("repo/patches/", [StringComparison]::Ordinal)) {
        "patches/btbn/$($Patch.relative_path.Substring("repo/patches/".Length))"
    }
    elseif ($Patch.relative_path.StartsWith("tooling/ffmpeg-build-patches/", [StringComparison]::Ordinal)) {
        "patches/splicr/$([IO.Path]::GetFileName($Patch.relative_path))"
    }
    else {
        throw "Unknown patch source path in evidence: $($Patch.relative_path)"
    }
    Assert-SafeRelativePath $RelativePath
    $Path = Join-Path $BundleDirectory $RelativePath
    Assert-Condition (Test-Path -LiteralPath $Path -PathType Leaf) "Bundled patch is missing: $RelativePath"
    Assert-Condition ((Get-Sha256 $Path) -eq $Patch.sha256) "Bundled patch hash mismatch: $RelativePath"
}

Write-Output "FFmpeg corresponding-source candidate passed complete-content and checksum validation. Public release gate remains open."
