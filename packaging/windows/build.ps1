[CmdletBinding()]
param(
    [string]$Version = "0.1.0",
    [string]$FfmpegBin = "",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$StudioWeb = Join-Path $Root "studio-web"
$VendorBin = Join-Path $PSScriptRoot "vendor\ffmpeg\bin"
$Dist = Join-Path $Root "dist"
$Portable = Join-Path $Dist "SPLICR Studio"

if ($Version -notmatch '^\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$') {
    throw "Version must look like 1.2.3 or 1.2.3-rc.1"
}

Push-Location $Root
try {
    & npm.cmd --prefix $StudioWeb ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    & npm.cmd --prefix $StudioWeb run build
    if ($LASTEXITCODE -ne 0) { throw "Studio web build failed" }

    New-Item -ItemType Directory -Force -Path $VendorBin | Out-Null
    Get-ChildItem -LiteralPath $VendorBin -File -ErrorAction SilentlyContinue | Remove-Item -Force
    $VendorMetadataRoot = Split-Path $VendorBin -Parent
    foreach ($Metadata in @("LICENSE.txt", "SOURCE_INFO.txt")) {
        $StaleMetadata = Join-Path $VendorMetadataRoot $Metadata
        if (Test-Path -LiteralPath $StaleMetadata) {
            Remove-Item -LiteralPath $StaleMetadata -Force
        }
    }
    if ($FfmpegBin) {
        $ResolvedFfmpegBin = (Resolve-Path -LiteralPath $FfmpegBin).Path
        foreach ($Tool in @("ffmpeg.exe", "ffprobe.exe")) {
            $Source = Join-Path $ResolvedFfmpegBin $Tool
            if (-not (Test-Path -LiteralPath $Source)) {
                throw "$Tool was not found in -FfmpegBin '$ResolvedFfmpegBin'."
            }
        }
        Get-ChildItem -LiteralPath $ResolvedFfmpegBin -File | Where-Object {
            $_.Name -in @("ffmpeg.exe", "ffprobe.exe") -or $_.Extension -eq ".dll"
        } | Copy-Item -Destination $VendorBin -Force
        $FfmpegRoot = Split-Path $ResolvedFfmpegBin -Parent
        foreach ($Metadata in @("LICENSE.txt", "SOURCE_INFO.txt")) {
            $Source = Join-Path $FfmpegRoot $Metadata
            $Destination = Join-Path $VendorMetadataRoot $Metadata
            if (Test-Path -LiteralPath $Source) {
                Copy-Item -LiteralPath $Source -Destination $Destination -Force
            }
        }
    }
    else {
        foreach ($Tool in @("ffmpeg.exe", "ffprobe.exe")) {
            $Command = Get-Command $Tool -ErrorAction SilentlyContinue
            if (-not $Command) {
                throw "$Tool is required to build the Windows package. Install FFmpeg and retry."
            }
            Copy-Item -LiteralPath $Command.Source -Destination (Join-Path $VendorBin $Tool) -Force
        }
    }
    $BundledFfmpeg = Join-Path $VendorBin "ffmpeg.exe"
    $BundledFfprobe = Join-Path $VendorBin "ffprobe.exe"
    $FfmpegInfo = & $BundledFfmpeg -version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Could not read the bundled FFmpeg version" }
    $FfprobeInfo = & $BundledFfprobe -version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Could not read the bundled FFprobe version" }
    @(
        "This file records the exact media tools copied into this SPLICR Studio build."
        ""
        "FFmpeg:"
        $FfmpegInfo
        ""
        "FFprobe:"
        $FfprobeInfo
    ) | Set-Content -LiteralPath (Join-Path (Split-Path $VendorBin -Parent) "BUILD_INFO.txt") -Encoding UTF8

    & uv.exe run --with "pyinstaller==6.16.0" pyinstaller --noconfirm --clean `
        (Join-Path $PSScriptRoot "splicr.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

    $SmokeData = Join-Path $env:TEMP "splicr-package-smoke-$PID"
    try {
        $PreviousDataDir = $env:SPLICR_DATA_DIR
        $env:SPLICR_DATA_DIR = $SmokeData
        & (Join-Path $Portable "SPLICR Studio.exe") --package-smoke-test
        if ($LASTEXITCODE -ne 0) { throw "Packaged application smoke test failed" }
    }
    finally {
        $env:SPLICR_DATA_DIR = $PreviousDataDir
        if (Test-Path -LiteralPath $SmokeData) {
            Remove-Item -LiteralPath $SmokeData -Recurse -Force
        }
    }

    $PortableZip = Join-Path $Dist "SPLICR-Studio-$Version-Windows-x64-portable.zip"
    if (Test-Path -LiteralPath $PortableZip) { Remove-Item -LiteralPath $PortableZip -Force }
    Compress-Archive -LiteralPath $Portable -DestinationPath $PortableZip -CompressionLevel Optimal

    if (-not $SkipInstaller) {
        $IsccOnPath = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        $IsccCandidates = @(
            @(
                $(if ($IsccOnPath) { $IsccOnPath.Source }),
                (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
                (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
                (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
            ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
        )
        if (-not $IsccCandidates) {
            throw "Inno Setup 6 was not found. Install it or pass -SkipInstaller."
        }
        & $IsccCandidates[0] "/DMyAppVersion=$Version" (Join-Path $PSScriptRoot "installer.iss")
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed" }
    }

    $Artifacts = Get-ChildItem -LiteralPath $Dist -File | Where-Object {
        $_.Name -like "SPLICR-Studio-$Version-Windows-x64*"
    }
    $ChecksumPath = Join-Path $Dist "SPLICR-Studio-$Version-SHA256SUMS.txt"
    $ChecksumLines = foreach ($Artifact in $Artifacts) {
        $Stream = [System.IO.File]::OpenRead($Artifact.FullName)
        try {
            $Sha = [System.Security.Cryptography.SHA256]::Create()
            try {
                $Bytes = $Sha.ComputeHash($Stream)
            }
            finally {
                $Sha.Dispose()
            }
        }
        finally {
            $Stream.Dispose()
        }
        $Hash = ($Bytes | ForEach-Object { $_.ToString("x2") }) -join ""
        "$Hash  $($Artifact.Name)"
    }
    Set-Content -LiteralPath $ChecksumPath -Value $ChecksumLines -Encoding UTF8
    Write-Host "Built Windows artifacts in $Dist"
}
finally {
    Pop-Location
}
