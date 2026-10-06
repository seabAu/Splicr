[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RebuildWorkspace,
    [string]$ImageTag = "ghcr.io/btbn/ffmpeg-builds/win64-lgpl-shared-9.0:latest",
    [string]$LogPath = "",
    [string]$PreparedDockerfilePath = "",
    # Podman 5.6.1 can panic while committing parallel Buildah stages.
    [ValidateRange(1, 64)]
    [int]$Jobs = 1,
    [switch]$PrepareOnly
)

$ErrorActionPreference = "Stop"
$Workspace = [IO.Path]::GetFullPath($RebuildWorkspace)
$Repository = Join-Path $Workspace "repo"
$DockerfilePath = Join-Path $Repository "Dockerfile"
$RunnerPath = Join-Path $Repository "util\run_stage.sh"
$BuildInputsPath = Join-Path $PSScriptRoot "ffmpeg-offline-build-inputs.json"
$BuildPatchesDirectory = Join-Path $PSScriptRoot "ffmpeg-build-patches"
$BuildSourcesDirectory = Join-Path $PSScriptRoot "ffmpeg-build-sources"

function Assert-Condition([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw $Message
    }
}

function ConvertTo-Lf([string]$Value) {
    return $Value.Replace("`r`n", "`n").Replace("`r", "`n")
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

function Get-OrdinalOccurrenceCount([string]$Value, [string]$Needle) {
    $Count = 0
    $Offset = 0
    while (($Offset = $Value.IndexOf($Needle, $Offset, [StringComparison]::Ordinal)) -ge 0) {
        $Count += 1
        $Offset += $Needle.Length
    }
    return $Count
}

Assert-Condition (Test-Path -LiteralPath $DockerfilePath -PathType Leaf) `
    "Missing generated dependency Dockerfile: $DockerfilePath"
Assert-Condition (Test-Path -LiteralPath $RunnerPath -PathType Leaf) `
    "Missing generated dependency runner: $RunnerPath"
Assert-Condition (Test-Path -LiteralPath (Join-Path $Repository ".cache\downloads") -PathType Container) `
    "Missing offline source archive cache under $Repository"
Assert-Condition (Test-Path -LiteralPath $BuildInputsPath -PathType Leaf) `
    "Missing offline build-input manifest: $BuildInputsPath"

$BuildInputs = [IO.File]::ReadAllText($BuildInputsPath) | ConvertFrom-Json
Assert-Condition ($BuildInputs.schema_version -eq 1) "Unsupported offline build-input manifest schema"
$PinnedInputs = @($BuildInputs.inputs)
Assert-Condition ($PinnedInputs.Count -eq 2) `
    "Expected exactly two pinned offline build inputs"
$OneVplInput = @($PinnedInputs | Where-Object { $_.stage -eq "scripts.d/50-onevpl.sh" })
Assert-Condition ($OneVplInput.Count -eq 1) `
    "Expected exactly one pinned oneVPL input"
$OneVplInput = $OneVplInput[0]
Assert-Condition ($OneVplInput.kind -eq "patch") `
    "The pinned oneVPL input must be a patch"
Assert-Condition ($OneVplInput.stage -eq "scripts.d/50-onevpl.sh") `
    "The pinned offline build input must target the oneVPL stage"
$PatchSourcePath = Join-Path $BuildPatchesDirectory $OneVplInput.filename
Assert-Condition (Test-Path -LiteralPath $PatchSourcePath -PathType Leaf) `
    "Missing pinned offline build input: $PatchSourcePath"
Assert-Condition ((Get-Sha256 $PatchSourcePath) -eq $OneVplInput.sha256) `
    "Pinned offline build-input hash mismatch: $PatchSourcePath"

$FreeTypeInput = @($PinnedInputs | Where-Object { $_.kind -eq "source_archive" })
Assert-Condition ($FreeTypeInput.Count -eq 1) `
    "Expected exactly one pinned FreeType input"
$FreeTypeInput = $FreeTypeInput[0]
Assert-Condition ($FreeTypeInput.kind -eq "source_archive") `
    "The pinned FreeType input must be a source archive"
$FreeTypeStages = @($FreeTypeInput.stages)
Assert-Condition ($FreeTypeStages.Count -eq 2) `
    "The pinned FreeType input must target both FreeType build stages"
Assert-Condition ($FreeTypeStages -contains "scripts.d/45-fonts/25-freetype.sh") `
    "The pinned FreeType input is missing the pre-HarfBuzz stage"
Assert-Condition ($FreeTypeStages -contains "scripts.d/45-fonts/50-freetype.sh") `
    "The pinned FreeType input is missing the post-HarfBuzz stage"
$FreeTypeSourcePath = Join-Path $BuildSourcesDirectory $FreeTypeInput.filename
Assert-Condition (Test-Path -LiteralPath $FreeTypeSourcePath -PathType Leaf) `
    "Missing pinned offline source input: $FreeTypeSourcePath"
Assert-Condition ((Get-Sha256 $FreeTypeSourcePath) -eq $FreeTypeInput.sha256) `
    "Pinned offline source-input hash mismatch: $FreeTypeSourcePath"

$OfflineInputsDirectory = Join-Path $Repository ".cache\offline-inputs"
$OfflineScriptsDirectory = Join-Path $Repository ".cache\offline-scripts"
New-Item -ItemType Directory -Path $OfflineInputsDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $OfflineScriptsDirectory -Force | Out-Null
$PatchContextPath = Join-Path $OfflineInputsDirectory $OneVplInput.filename
[IO.File]::Copy($PatchSourcePath, $PatchContextPath, $true)
$FreeTypeContextPath = Join-Path $OfflineInputsDirectory $FreeTypeInput.filename
[IO.File]::Copy($FreeTypeSourcePath, $FreeTypeContextPath, $true)

$OneVplStagePath = Join-Path $Repository ($OneVplInput.stage.Replace("/", "\"))
Assert-Condition (Test-Path -LiteralPath $OneVplStagePath -PathType Leaf) `
    "Missing pinned oneVPL stage script: $OneVplStagePath"
$OneVplStage = ConvertTo-Lf ([IO.File]::ReadAllText($OneVplStagePath))
$PatchFetchNeedle = "    curl -fL $($OneVplInput.source_url) | git am"
$PatchApplyReplacement = "    git am /offline-inputs/$($OneVplInput.filename)"
Assert-Condition ((Get-OrdinalOccurrenceCount $OneVplStage $PatchFetchNeedle) -eq 1) `
    "The oneVPL recipe must contain exactly one expected live patch fetch"
$AdaptedOneVplStage = $OneVplStage.Replace($PatchFetchNeedle, $PatchApplyReplacement)
Assert-Condition ($AdaptedOneVplStage.IndexOf("`r", [StringComparison]::Ordinal) -lt 0) `
    "The adapted oneVPL stage contains a carriage return"
$OneVplContextPath = Join-Path $OfflineScriptsDirectory "50-onevpl.sh"
[IO.File]::WriteAllText($OneVplContextPath, $AdaptedOneVplStage, [Text.UTF8Encoding]::new($false))

$FreeTypeAutogenNeedle = "    ./autogen.sh"
$FreeTypeAutogenReplacement = ConvertTo-Lf @"
    rm -rf subprojects/dlg
    mkdir -p subprojects/dlg
    tar xaf /offline-inputs/$($FreeTypeInput.filename) -C subprojects/dlg --strip-components=1
    ./autogen.sh
"@
foreach ($FreeTypeStageName in $FreeTypeStages) {
    $FreeTypeStagePath = Join-Path $Repository ($FreeTypeStageName.Replace("/", "\"))
    Assert-Condition (Test-Path -LiteralPath $FreeTypeStagePath -PathType Leaf) `
        "Missing pinned FreeType stage script: $FreeTypeStagePath"
    $FreeTypeStage = ConvertTo-Lf ([IO.File]::ReadAllText($FreeTypeStagePath))
    Assert-Condition ((Get-OrdinalOccurrenceCount $FreeTypeStage $FreeTypeAutogenNeedle) -eq 1) `
        "The FreeType recipe must contain exactly one expected autogen invocation: $FreeTypeStageName"
    $AdaptedFreeTypeStage = $FreeTypeStage.Replace(
        $FreeTypeAutogenNeedle,
        $FreeTypeAutogenReplacement
    )
    Assert-Condition ($AdaptedFreeTypeStage.IndexOf("`r", [StringComparison]::Ordinal) -lt 0) `
        "The adapted FreeType stage contains a carriage return: $FreeTypeStageName"
    $FreeTypeContextStagePath = Join-Path `
        $OfflineScriptsDirectory `
        ([IO.Path]::GetFileName($FreeTypeStageName))
    [IO.File]::WriteAllText(
        $FreeTypeContextStagePath,
        $AdaptedFreeTypeStage,
        [Text.UTF8Encoding]::new($false)
    )
}

$Runner = ConvertTo-Lf ([IO.File]::ReadAllText($RunnerPath))
$ExtractionNeedle = ConvertTo-Lf @'
    tar xaf /cache.tar.xz -C "/$STAGENAME"
    cd "/$STAGENAME"
'@
$ExtractionReplacement = ConvertTo-Lf @'
    tar xaf /cache.tar.xz -C "/$STAGENAME"
    cd "/$STAGENAME"
    mapfile -d '' roots < <(find . -mindepth 1 -maxdepth 1 -print0)
    if [[ ${#roots[@]} -eq 1 && -d "${roots[0]}" ]]; then
        cd "${roots[0]}"
    fi
'@
Assert-Condition ((Get-OrdinalOccurrenceCount $Runner $ExtractionNeedle) -eq 1) `
    "The generated runner must contain exactly one expected archive-extraction block"
$AdaptedRunner = $Runner.Replace($ExtractionNeedle, $ExtractionReplacement)
Assert-Condition ($AdaptedRunner.IndexOf("`r", [StringComparison]::Ordinal) -lt 0) `
    "The adapted runner contains a carriage return"
Assert-Condition ($AdaptedRunner.IndexOf('mapfile -d '''' roots', [StringComparison]::Ordinal) -ge 0) `
    "The single-root archive adaptation was not applied"

$Utf8NoBom = [Text.UTF8Encoding]::new($false)
$RunnerBase64 = [Convert]::ToBase64String($Utf8NoBom.GetBytes($AdaptedRunner))
$Dockerfile = ConvertTo-Lf ([IO.File]::ReadAllText($DockerfilePath))
$CopyNeedle = "COPY --link util/run_stage.sh /usr/bin/run_stage"
$CopyReplacement = "RUN printf '%s' '$RunnerBase64' | base64 -d > /usr/bin/run_stage && chmod 0755 /usr/bin/run_stage"
Assert-Condition ((Get-OrdinalOccurrenceCount $Dockerfile $CopyNeedle) -eq 1) `
    "The generated Dockerfile must contain exactly one expected runner COPY instruction"
$PreparedDockerfile = $Dockerfile.Replace($CopyNeedle, $CopyReplacement)
$OneVplMountNeedle = "--mount=src=scripts.d/50-onevpl.sh,dst=/stage.sh"
$OneVplMountReplacement = `
    "--mount=src=.cache/offline-scripts/50-onevpl.sh,dst=/stage.sh " + `
    "--mount=src=.cache/offline-inputs/$($OneVplInput.filename),dst=/offline-inputs/$($OneVplInput.filename)"
Assert-Condition ((Get-OrdinalOccurrenceCount $PreparedDockerfile $OneVplMountNeedle) -eq 1) `
    "The generated Dockerfile must contain exactly one expected oneVPL stage mount"
$PreparedDockerfile = $PreparedDockerfile.Replace($OneVplMountNeedle, $OneVplMountReplacement)
foreach ($FreeTypeStageName in $FreeTypeStages) {
    $FreeTypeStageFile = [IO.Path]::GetFileName($FreeTypeStageName)
    $FreeTypeMountNeedle = "--mount=src=$FreeTypeStageName,dst=/stage.sh"
    $FreeTypeMountReplacement = `
        "--mount=src=.cache/offline-scripts/$FreeTypeStageFile,dst=/stage.sh " + `
        "--mount=src=.cache/offline-inputs/$($FreeTypeInput.filename),dst=/offline-inputs/$($FreeTypeInput.filename)"
    Assert-Condition ((Get-OrdinalOccurrenceCount $PreparedDockerfile $FreeTypeMountNeedle) -eq 1) `
        "The generated Dockerfile must contain exactly one expected FreeType stage mount: $FreeTypeStageName"
    $PreparedDockerfile = $PreparedDockerfile.Replace($FreeTypeMountNeedle, $FreeTypeMountReplacement)
}
Assert-Condition ($PreparedDockerfile.IndexOf("`r", [StringComparison]::Ordinal) -lt 0) `
    "The prepared Dockerfile contains a carriage return"

$RemovePreparedDockerfile = $false
if ($PreparedDockerfilePath) {
    $PreparedDockerfilePath = [IO.Path]::GetFullPath($PreparedDockerfilePath)
}
else {
    $PreparedDockerfilePath = Join-Path ([IO.Path]::GetTempPath()) "splicr-ffmpeg-dependencies-$PID.Dockerfile"
    $RemovePreparedDockerfile = -not $PrepareOnly
}
[IO.File]::WriteAllText($PreparedDockerfilePath, $PreparedDockerfile, $Utf8NoBom)
Write-Output "Prepared LF-only offline Dockerfile: $PreparedDockerfilePath"

if ($PrepareOnly) {
    return
}

if (-not $LogPath) {
    $LogPath = Join-Path $Workspace "podman-offline-dependencies.log"
}
$LogPath = [IO.Path]::GetFullPath($LogPath)

try {
    & podman build `
        --platform linux/amd64 `
        --pull=never `
        --network=none `
        --jobs $Jobs `
        --logfile $LogPath `
        --tag $ImageTag `
        --file $PreparedDockerfilePath `
        $Repository
    if ($LASTEXITCODE -ne 0) {
        throw "Offline Podman dependency build failed with exit code $LASTEXITCODE. See $LogPath"
    }
}
finally {
    if ($RemovePreparedDockerfile) {
        Remove-Item -LiteralPath $PreparedDockerfilePath -Force -ErrorAction SilentlyContinue
    }
}

Write-Output "Built offline dependency image: $ImageTag"
Write-Output "Build log: $LogPath"
