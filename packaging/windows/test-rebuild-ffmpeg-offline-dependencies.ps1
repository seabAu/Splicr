$ErrorActionPreference = "Stop"
$HelperPath = Join-Path $PSScriptRoot "rebuild-ffmpeg-offline-dependencies.ps1"
$TestRoot = Join-Path ([IO.Path]::GetTempPath()) "splicr-ffmpeg-offline-helper-$PID"
$Repository = Join-Path $TestRoot "repo"
$RunnerDirectory = Join-Path $Repository "util"
$StageDirectory = Join-Path $Repository "scripts.d"
$DownloadsDirectory = Join-Path $Repository ".cache\downloads"
$PreparedDockerfilePath = Join-Path $TestRoot "Dockerfile.prepared"
$Utf8NoBom = [Text.UTF8Encoding]::new($false)

function Assert-Condition([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw $Message
    }
}

try {
    New-Item -ItemType Directory -Path $RunnerDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $StageDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $DownloadsDirectory -Force | Out-Null

    $Dockerfile = @'
FROM scratch AS base-layer
COPY --link util/run_stage.sh /usr/bin/run_stage
FROM base-layer AS onevpl
ENV SELF="scripts.d/50-onevpl.sh" STAGENAME="50-onevpl"
RUN --mount=src=scripts.d/50-onevpl.sh,dst=/stage.sh --mount=src=.cache/downloads/50-onevpl_test.tar.xz,dst=/cache.tar.xz run_stage /stage.sh
FROM base-layer AS fonts
ENV SELF="scripts.d/45-fonts/25-freetype.sh" STAGENAME="25-freetype"
RUN --mount=src=scripts.d/45-fonts/25-freetype.sh,dst=/stage.sh --mount=src=.cache/downloads/25-freetype_test.tar.xz,dst=/cache.tar.xz run_stage /stage.sh
ENV SELF="scripts.d/45-fonts/50-freetype.sh" STAGENAME="50-freetype"
RUN --mount=src=scripts.d/45-fonts/50-freetype.sh,dst=/stage.sh --mount=src=.cache/downloads/50-freetype_test.tar.xz,dst=/cache.tar.xz run_stage /stage.sh
'@
    $Runner = @'
#!/bin/bash
set -xe
if [[ -n "$STAGENAME" && -f /cache.tar.xz ]]; then
    mkdir -p "/$STAGENAME"
    tar xaf /cache.tar.xz -C "/$STAGENAME"
    cd "/$STAGENAME"
elif [[ -n "$STAGENAME" ]]; then
    mkdir -p "/$STAGENAME"
    cd "/$STAGENAME"
fi
source "$1"
'@
    $OneVplStage = @'
#!/bin/bash
ffbuild_dockerbuild() {
    curl -fL https://github.com/intel/libvpl/pull/198.patch | git am
}
'@
    $FreeTypeStage = @'
#!/bin/bash
ffbuild_dockerbuild() {
    ./autogen.sh
}
'@
    [IO.File]::WriteAllText((Join-Path $Repository "Dockerfile"), $Dockerfile, $Utf8NoBom)
    [IO.File]::WriteAllText((Join-Path $RunnerDirectory "run_stage.sh"), $Runner, $Utf8NoBom)
    [IO.File]::WriteAllText((Join-Path $StageDirectory "50-onevpl.sh"), $OneVplStage, $Utf8NoBom)
    New-Item -ItemType Directory -Path (Join-Path $StageDirectory "45-fonts") -Force | Out-Null
    [IO.File]::WriteAllText(
        (Join-Path $StageDirectory "45-fonts\25-freetype.sh"),
        $FreeTypeStage,
        $Utf8NoBom
    )
    [IO.File]::WriteAllText(
        (Join-Path $StageDirectory "45-fonts\50-freetype.sh"),
        $FreeTypeStage,
        $Utf8NoBom
    )

    & $HelperPath `
        -RebuildWorkspace $TestRoot `
        -PreparedDockerfilePath $PreparedDockerfilePath `
        -PrepareOnly | Out-Null

    $PreparedBytes = [IO.File]::ReadAllBytes($PreparedDockerfilePath)
    Assert-Condition (-not ($PreparedBytes -contains 13)) `
        "Prepared Dockerfile must contain LF line endings only"
    $PreparedText = [Text.Encoding]::UTF8.GetString($PreparedBytes)
    $Match = [regex]::Match($PreparedText, "RUN printf '%s' '([^']+)' \| base64 -d")
    Assert-Condition $Match.Success "Prepared Dockerfile does not embed the adapted runner"

    $AdaptedBytes = [Convert]::FromBase64String($Match.Groups[1].Value)
    Assert-Condition (-not ($AdaptedBytes -contains 13)) `
        "Adapted runner must contain LF line endings only"
    $AdaptedRunner = [Text.Encoding]::UTF8.GetString($AdaptedBytes)
    Assert-Condition ($AdaptedRunner.IndexOf("mapfile -d '' roots", [StringComparison]::Ordinal) -ge 0) `
        "Adapted runner does not enumerate extracted archive roots"
    Assert-Condition ($AdaptedRunner.IndexOf('if [[ ${#roots[@]} -eq 1', [StringComparison]::Ordinal) -ge 0) `
        "Adapted runner does not descend into a sole extracted directory"

    Assert-Condition ($PreparedText.IndexOf(
        "--mount=src=.cache/offline-inputs/onevpl-pr-198.patch,dst=/offline-inputs/onevpl-pr-198.patch",
        [StringComparison]::Ordinal
    ) -ge 0) "Prepared Dockerfile does not mount the pinned oneVPL patch"
    $AdaptedOneVplStage = [IO.File]::ReadAllText(
        (Join-Path $Repository ".cache\offline-scripts\50-onevpl.sh")
    )
    Assert-Condition ($AdaptedOneVplStage.IndexOf(
        "git am /offline-inputs/onevpl-pr-198.patch",
        [StringComparison]::Ordinal
    ) -ge 0) "Adapted oneVPL stage does not apply the pinned local patch"
    Assert-Condition ($AdaptedOneVplStage.IndexOf("curl -fL", [StringComparison]::Ordinal) -lt 0) `
        "Adapted oneVPL stage still performs a live patch fetch"
    $PinnedPatch = Join-Path $PSScriptRoot "ffmpeg-build-patches\onevpl-pr-198.patch"
    $ContextPatch = Join-Path $Repository ".cache\offline-inputs\onevpl-pr-198.patch"
    Assert-Condition (
        [Convert]::ToBase64String([IO.File]::ReadAllBytes($PinnedPatch)) -eq
        [Convert]::ToBase64String([IO.File]::ReadAllBytes($ContextPatch))
    ) "Pinned oneVPL patch changed while being copied into the build context"

    $DlgFilename = "dlg-395ccad2c1e0daae535c4d20bb0a3f2424648e17.tar.gz"
    $DlgMount = "--mount=src=.cache/offline-inputs/$DlgFilename,dst=/offline-inputs/$DlgFilename"
    Assert-Condition (
        ([regex]::Matches($PreparedText, [regex]::Escape($DlgMount))).Count -eq 2
    ) "Prepared Dockerfile does not mount the pinned dlg source for both FreeType stages"
    foreach ($FreeTypeStageFile in @("25-freetype.sh", "50-freetype.sh")) {
        $AdaptedFreeTypeStage = [IO.File]::ReadAllText(
            (Join-Path $Repository ".cache\offline-scripts\$FreeTypeStageFile")
        )
        Assert-Condition ($AdaptedFreeTypeStage.IndexOf(
            "tar xaf /offline-inputs/$DlgFilename -C subprojects/dlg --strip-components=1",
            [StringComparison]::Ordinal
        ) -ge 0) "Adapted $FreeTypeStageFile does not extract the pinned dlg source"
    }
    $PinnedDlg = Join-Path $PSScriptRoot "ffmpeg-build-sources\$DlgFilename"
    $ContextDlg = Join-Path $Repository ".cache\offline-inputs\$DlgFilename"
    Assert-Condition (
        [Convert]::ToBase64String([IO.File]::ReadAllBytes($PinnedDlg)) -eq
        [Convert]::ToBase64String([IO.File]::ReadAllBytes($ContextDlg))
    ) "Pinned FreeType dlg source changed while being copied into the build context"

    Write-Output "Offline FFmpeg dependency rebuild helper passed."
}
finally {
    Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue
}
