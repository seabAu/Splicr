[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [Parameter(Mandatory = $true)]
    [string]$CollectionRoot,
    [Parameter(Mandatory = $true)]
    [string]$PrimarySourceDirectory,
    [Parameter(Mandatory = $true)]
    [string]$RebuildWorkspace,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [switch]$UseHardLinks,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7 or newer is required. Run this script with pwsh."
}
if ($Version -notmatch '^\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$') {
    throw "Version must look like 1.2.3 or 1.2.3-rc.1"
}

$CollectionRoot = [IO.Path]::GetFullPath($CollectionRoot)
$PrimarySourceDirectory = [IO.Path]::GetFullPath($PrimarySourceDirectory)
$RebuildWorkspace = [IO.Path]::GetFullPath($RebuildWorkspace)
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$LockPath = Join-Path $PSScriptRoot "ffmpeg-source-lock.json"
$EvidencePath = Join-Path $PSScriptRoot "ffmpeg-correspondence-evidence.json"
$ReadmePath = Join-Path $PSScriptRoot "FFMPEG_CORRESPONDING_SOURCE_README.md"

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

function Assert-File([string]$Path, [string]$Description) {
    Assert-Condition (Test-Path -LiteralPath $Path -PathType Leaf) "Missing $Description`: $Path"
}

function Assert-HashAndSize([string]$Path, [string]$ExpectedHash, [long]$ExpectedSize) {
    Assert-File $Path "evidence file"
    $Item = Get-Item -LiteralPath $Path
    Assert-Condition ($Item.Length -eq $ExpectedSize) `
        "Size mismatch for $Path`: expected $ExpectedSize, received $($Item.Length)"
    $ActualHash = Get-Sha256 $Path
    Assert-Condition ($ActualHash -eq $ExpectedHash) `
        "SHA-256 mismatch for $Path`: expected $ExpectedHash, received $ActualHash"
}

function Assert-SafeRelativePath([string]$RelativePath) {
    Assert-Condition (-not [IO.Path]::IsPathRooted($RelativePath)) "Rooted path is forbidden: $RelativePath"
    $Segments = $RelativePath.Replace("\", "/").Split("/", [StringSplitOptions]::RemoveEmptyEntries)
    Assert-Condition ($Segments.Count -gt 0 -and -not ($Segments -contains "..")) `
        "Unsafe relative path: $RelativePath"
}

function Copy-BundleFile([string]$Source, [string]$Destination) {
    $Parent = Split-Path $Destination -Parent
    New-Item -ItemType Directory -Force -Path $Parent | Out-Null
    if ($UseHardLinks) {
        try {
            New-Item -ItemType HardLink -Path $Destination -Target $Source -ErrorAction Stop | Out-Null
            return
        }
        catch {
            Write-Verbose "Hard-link creation failed for $Source; falling back to a copy."
        }
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

foreach ($RequiredFile in @($LockPath, $EvidencePath, $ReadmePath)) {
    Assert-File $RequiredFile "tracked corresponding-source input"
}
foreach ($RequiredDirectory in @($CollectionRoot, $PrimarySourceDirectory, $RebuildWorkspace)) {
    Assert-Condition (Test-Path -LiteralPath $RequiredDirectory -PathType Container) `
        "Required directory not found: $RequiredDirectory"
}

$Lock = Get-Content -Raw -LiteralPath $LockPath | ConvertFrom-Json
$Evidence = Get-Content -Raw -LiteralPath $EvidencePath | ConvertFrom-Json
Assert-Condition ($Lock.dependency_graph.enabled_stage_count -eq 90) "Unexpected enabled-stage count in source lock"
Assert-Condition ($Lock.dependency_graph.source_locator_count -eq 92) "Unexpected source-locator count in source lock"
Assert-Condition ($Evidence.source_commit -eq $Lock.primary_source_archives[0].commit) `
    "Correspondence evidence does not match the pinned FFmpeg source"
Assert-Condition ($Evidence.dependency_recipe_commit -eq $Lock.primary_source_archives[2].commit) `
    "Correspondence evidence does not match the pinned BtbN recipe"

$CollectionInfoPath = Join-Path $CollectionRoot "COLLECTION_INFO.txt"
$CollectionPlanPath = Join-Path $CollectionRoot "collection-plan.tsv"
$CollectionManifestPath = Join-Path $CollectionRoot "collection-manifest.tsv"
$CollectionChecksumsPath = Join-Path $CollectionRoot "COLLECTION-SHA256SUMS.txt"
$CandidateInventoryPath = Join-Path $CollectionRoot "license-candidate-inventory.tsv"
foreach ($RequiredFile in @(
    $CollectionInfoPath,
    $CollectionPlanPath,
    $CollectionManifestPath,
    $CollectionChecksumsPath,
    $CandidateInventoryPath
)) {
    Assert-File $RequiredFile "collection evidence"
}

$CollectionInfo = Get-Content -Raw -LiteralPath $CollectionInfoPath
foreach ($RequiredLine in @(
    "State: sources-collected-unreviewed",
    "Scope: full-graph",
    "Tracked enabled stage count: 90",
    "Selected stage count: 90",
    "Selected source-bearing stage count: 85",
    "Pending source-bearing stage count: 0"
)) {
    Assert-Condition ($CollectionInfo.Contains($RequiredLine, [StringComparison]::Ordinal)) `
        "COLLECTION_INFO.txt is missing required line: $RequiredLine"
}

$CollectionRows = @(Import-Csv -LiteralPath $CollectionManifestPath -Delimiter "`t")
Assert-Condition ($CollectionRows.Count -eq 90) "Collection manifest must contain exactly 90 stages"
$CollectedRows = @($CollectionRows | Where-Object { $_.source_status -eq "collected" })
Assert-Condition ($CollectedRows.Count -eq 85) "Collection manifest must contain exactly 85 collected source archives"
Assert-Condition ((Get-Sha256 $CollectionManifestPath) -eq $Evidence.validated_collection.collection_manifest_sha256) `
    "Collection manifest does not match the reviewed correspondence evidence"
Assert-Condition ((Get-Sha256 $CollectionPlanPath) -eq $Evidence.validated_collection.collection_plan_sha256) `
    "Collection plan does not match the reviewed correspondence evidence"
Assert-Condition ((Get-Sha256 $CollectionChecksumsPath) -eq $Evidence.validated_collection.collection_checksums_sha256) `
    "Collection checksum manifest does not match the reviewed correspondence evidence"
Assert-Condition ((Get-Sha256 $CandidateInventoryPath) -eq $Evidence.validated_collection.candidate_inventory_sha256) `
    "Candidate inventory does not match the 1,684-row reviewed evidence"
foreach ($Row in $CollectedRows) {
    Assert-SafeRelativePath $Row.archive_name
    $ArchivePath = Join-Path (Join-Path $CollectionRoot "stages") $Row.archive_name
    Assert-File $ArchivePath "collected source archive"
    Assert-Condition ((Get-Sha256 $ArchivePath) -eq $Row.archive_sha256) `
        "Collected archive hash mismatch: $($Row.archive_name)"
}

$ChecksumLines = @(Get-Content -LiteralPath $CollectionChecksumsPath | Where-Object { $_.Trim() })
Assert-Condition ($ChecksumLines.Count -eq 87) "Collection checksum manifest must contain exactly 87 records"
foreach ($Line in $ChecksumLines) {
    $Parts = $Line -split '\s+', 2
    Assert-Condition ($Parts.Count -eq 2 -and $Parts[0] -match '^[0-9a-f]{64}$') `
        "Malformed collection checksum line: $Line"
    $RelativePath = $Parts[1].Trim()
    Assert-SafeRelativePath $RelativePath
    $Path = Join-Path $CollectionRoot $RelativePath
    Assert-File $Path "collection checksum target"
    Assert-Condition ((Get-Sha256 $Path) -eq $Parts[0]) "Collection checksum mismatch: $RelativePath"
}

foreach ($Archive in $Lock.primary_source_archives) {
    $Path = Join-Path $PrimarySourceDirectory $Archive.filename
    Assert-File $Path "pinned primary source archive"
    Assert-Condition ((Get-Sha256 $Path) -eq $Archive.sha256) `
        "Primary source archive hash mismatch: $($Archive.filename)"
}
foreach ($File in $Evidence.files) {
    Assert-SafeRelativePath $File.relative_path
    Assert-HashAndSize (Join-Path $RebuildWorkspace $File.relative_path) $File.sha256 $File.size_bytes
}
foreach ($Patch in $Evidence.patches) {
    Assert-SafeRelativePath $Patch.relative_path
    $PatchPath = if ($Patch.relative_path.StartsWith("tooling/", [StringComparison]::Ordinal)) {
        Join-Path $PSScriptRoot $Patch.relative_path.Substring("tooling/".Length)
    }
    else {
        Join-Path $RebuildWorkspace $Patch.relative_path
    }
    Assert-File $PatchPath "recorded patch"
    Assert-Condition ((Get-Sha256 $PatchPath) -eq $Patch.sha256) `
        "Patch hash mismatch: $($Patch.relative_path)"
}
foreach ($TrackedReview in @(
    @{ Name = "ffmpeg-source-license-review.tsv"; Hash = $Evidence.validated_collection.license_review_sha256 },
    @{ Name = "THIRD_PARTY_NOTICES.md"; Hash = $Evidence.validated_collection.third_party_notices_sha256 },
    @{ Name = "validate-ffmpeg-source-license-review.sh"; Hash = $Evidence.validated_collection.review_validator_sha256 },
    @{ Name = "ffmpeg-source-locator-aliases.tsv"; Hash = $Evidence.validated_collection.source_locator_aliases_sha256 },
    @{ Name = "ffmpeg-packaged-license-files.tsv"; Hash = $Evidence.validated_collection.packaged_license_files_sha256 },
    @{ Name = "ffmpeg-packaged-license-companions.tsv"; Hash = $Evidence.validated_collection.packaged_license_companions_sha256 }
)) {
    $TrackedPath = Join-Path $PSScriptRoot $TrackedReview.Name
    Assert-File $TrackedPath "tracked review input"
    Assert-Condition ((Get-Sha256 $TrackedPath) -eq $TrackedReview.Hash) `
        "Tracked review input changed after full-collection validation: $($TrackedReview.Name)"
}

if (Test-Path -LiteralPath $OutputDirectory) {
    Assert-Condition $Force "Output directory already exists; pass -Force to replace it: $OutputDirectory"
    Remove-Item -LiteralPath $OutputDirectory -Recurse -Force
}
$OutputParent = Split-Path $OutputDirectory -Parent
New-Item -ItemType Directory -Force -Path $OutputParent | Out-Null
$StagingRoot = "$OutputDirectory.staging-$PID"
if (Test-Path -LiteralPath $StagingRoot) {
    Remove-Item -LiteralPath $StagingRoot -Recurse -Force
}

try {
    New-Item -ItemType Directory -Force -Path $StagingRoot | Out-Null
    Copy-Item -LiteralPath $ReadmePath -Destination (Join-Path $StagingRoot "README.md")

    $DependencyRoot = Join-Path $StagingRoot "dependency-sources"
    New-Item -ItemType Directory -Force -Path (Join-Path $DependencyRoot "stages") | Out-Null
    foreach ($Name in @(
        "COLLECTION_INFO.txt",
        "collection-plan.tsv",
        "collection-manifest.tsv",
        "COLLECTION-SHA256SUMS.txt",
        "license-candidate-inventory.tsv",
        "license-review-template.tsv"
    )) {
        $Source = Join-Path $CollectionRoot $Name
        if (Test-Path -LiteralPath $Source -PathType Leaf) {
            Copy-BundleFile $Source (Join-Path $DependencyRoot $Name)
        }
    }
    foreach ($Row in $CollectedRows) {
        Copy-BundleFile `
            (Join-Path (Join-Path $CollectionRoot "stages") $Row.archive_name) `
            (Join-Path (Join-Path $DependencyRoot "stages") $Row.archive_name)
    }

    $PrimaryRoot = Join-Path $StagingRoot "primary-sources"
    New-Item -ItemType Directory -Force -Path $PrimaryRoot | Out-Null
    foreach ($Archive in $Lock.primary_source_archives) {
        Copy-BundleFile `
            (Join-Path $PrimarySourceDirectory $Archive.filename) `
            (Join-Path $PrimaryRoot $Archive.filename)
    }

    $ToolingRoot = Join-Path $StagingRoot "tooling"
    New-Item -ItemType Directory -Force -Path $ToolingRoot | Out-Null
    foreach ($Name in @(
        "ffmpeg-source-lock.json",
        "ffmpeg-correspondence-evidence.json",
        "ffmpeg-source-license-review.tsv",
        "ffmpeg-source-locator-aliases.tsv",
        "ffmpeg-packaged-license-files.tsv",
        "ffmpeg-packaged-license-companions.tsv",
        "ffmpeg-cargo-source-closure.tsv",
        "ffmpeg-cargo-source-supplements.tsv",
        "ffmpeg-offline-build-inputs.json",
        "THIRD_PARTY_NOTICES.md",
        "README.md",
        "collect-ffmpeg-source-graph.sh",
        "inventory-ffmpeg-source-licenses.sh",
        "validate-ffmpeg-collected-archive.sh",
        "validate-ffmpeg-source-license-review.sh",
        "rebuild-ffmpeg-offline-dependencies.ps1"
    )) {
        $Source = Join-Path $PSScriptRoot $Name
        Assert-File $Source "tracked tooling file"
        Copy-Item -LiteralPath $Source -Destination (Join-Path $ToolingRoot $Name)
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "ffmpeg-source-graph") `
        -Destination (Join-Path $ToolingRoot "ffmpeg-source-graph") -Recurse
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "ffmpeg-build-patches") `
        -Destination (Join-Path $ToolingRoot "ffmpeg-build-patches") -Recurse

    $PatchesRoot = Join-Path $StagingRoot "patches"
    New-Item -ItemType Directory -Force -Path $PatchesRoot | Out-Null
    Copy-Item -LiteralPath (Join-Path $RebuildWorkspace "repo\patches") `
        -Destination (Join-Path $PatchesRoot "btbn") -Recurse
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "ffmpeg-build-patches") `
        -Destination (Join-Path $PatchesRoot "splicr") -Recurse

    $BuildEvidenceRoot = Join-Path $StagingRoot "build-evidence"
    New-Item -ItemType Directory -Force -Path $BuildEvidenceRoot | Out-Null
    foreach ($File in $Evidence.files | Where-Object { $_.include_in_source_bundle }) {
        Copy-BundleFile `
            (Join-Path $RebuildWorkspace $File.relative_path) `
            (Join-Path $BuildEvidenceRoot ([IO.Path]::GetFileName($File.relative_path)))
    }

    $Manifest = [ordered]@{
        schema_version = 1
        package_version = $Version
        generated_at = [DateTimeOffset]::UtcNow.ToString("O")
        status = "corresponding-source-complete-publication-pending"
        binary = $Lock.binary
        primary_source_archives = $Lock.primary_source_archives
        dependency_graph = $Lock.dependency_graph
        collection = [ordered]@{
            enabled_stage_count = $Evidence.validated_collection.enabled_stage_count
            source_bearing_stage_count = $Evidence.validated_collection.source_bearing_stage_count
            source_locator_count = $Evidence.validated_collection.source_locator_count
            reviewed_candidate_count = $Evidence.validated_collection.reviewed_candidate_count
            manifest_sha256 = Get-Sha256 $CollectionManifestPath
            candidate_inventory_sha256 = Get-Sha256 $CandidateInventoryPath
        }
        correspondence_evidence = $Evidence
        completeness = [ordered]@{
            primary_sources_pinned = $true
            build_recipe_pinned = $true
            enabled_external_dependency_graph_generated = $true
            all_enabled_external_dependency_sources_included = $true
            license_and_notice_review_complete = $true
            correspondence_rebuild_verified = $true
            corresponding_source_complete = $true
            public_release_gate_satisfied = $false
        }
    }
    $Manifest | ConvertTo-Json -Depth 20 | Set-Content `
        -LiteralPath (Join-Path $StagingRoot "SOURCE_MANIFEST.json") -Encoding utf8NoBOM

    $BundleFiles = @(Get-ChildItem -LiteralPath $StagingRoot -File -Recurse | Sort-Object FullName)
    $ChecksumPath = Join-Path $StagingRoot "SOURCE-SHA256SUMS.txt"
    $ChecksumLines = foreach ($File in $BundleFiles) {
        $RelativePath = [IO.Path]::GetRelativePath($StagingRoot, $File.FullName).Replace("\", "/")
        "$(Get-Sha256 $File.FullName)  $RelativePath"
    }
    $ChecksumLines | Set-Content -LiteralPath $ChecksumPath -Encoding ascii

    Move-Item -LiteralPath $StagingRoot -Destination $OutputDirectory
    Write-Output $OutputDirectory
}
catch {
    if (Test-Path -LiteralPath $StagingRoot) {
        Remove-Item -LiteralPath $StagingRoot -Recurse -Force
    }
    throw
}
