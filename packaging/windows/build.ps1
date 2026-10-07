[CmdletBinding()]
param(
    [string]$Version = "0.1.0",
    [string]$FfmpegBin = "",
    [string]$CorrespondingSourceUrl = "",
    [string]$CorrespondingSourceSha256 = "",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$StudioWeb = Join-Path $Root "studio-web"
$VendorBin = Join-Path $PSScriptRoot "vendor\ffmpeg\bin"
$PackagedLicenseManifest = Join-Path $PSScriptRoot "ffmpeg-packaged-license-files.tsv"
$PackagedLicenseRecords = @(Import-Csv -LiteralPath $PackagedLicenseManifest -Delimiter "`t")
$RequiredMetadataNames = @(
    $PackagedLicenseRecords | ForEach-Object { Split-Path $_.package_path -Leaf }
)
$Dist = Join-Path $Root "dist"
$Portable = Join-Path $Dist "SPLICR Studio"
$ApplicationLicense = Join-Path $Root "LICENSE.txt"

if ($Version -notmatch '^\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$') {
    throw "Version must look like 1.2.3 or 1.2.3-rc.1"
}
if (-not (Test-Path -LiteralPath $ApplicationLicense -PathType Leaf)) {
    throw "The Apache-2.0 application license is required: $ApplicationLicense"
}
$ApplicationLicenseSha256 = (Get-FileHash -LiteralPath $ApplicationLicense -Algorithm SHA256).Hash.ToLowerInvariant()
if ([bool]$CorrespondingSourceUrl -ne [bool]$CorrespondingSourceSha256) {
    throw "CorrespondingSourceUrl and CorrespondingSourceSha256 must be provided together."
}
if ($CorrespondingSourceUrl) {
    $ParsedSourceUrl = $null
    if (-not [Uri]::TryCreate($CorrespondingSourceUrl, [UriKind]::Absolute, [ref]$ParsedSourceUrl) -or
        $ParsedSourceUrl.Scheme -ne "https" -or -not $ParsedSourceUrl.Host -or
        -not [string]::IsNullOrEmpty($ParsedSourceUrl.UserInfo)) {
        throw "CorrespondingSourceUrl must be an HTTPS URL without embedded credentials."
    }
    if ($CorrespondingSourceSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "CorrespondingSourceSha256 must be a 64-character SHA-256 digest."
    }
    $CorrespondingSourceSha256 = $CorrespondingSourceSha256.ToLowerInvariant()
}

Push-Location $Root
try {
    & npm.cmd --prefix $StudioWeb ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    & npm.cmd --prefix $StudioWeb run build
    if ($LASTEXITCODE -ne 0) { throw "Studio web build failed" }

    $ResolvedFfmpegBin = $null
    if ($FfmpegBin) {
        $ResolvedFfmpegBin = (Resolve-Path -LiteralPath $FfmpegBin).Path
        $ResolvedVendorBin = [IO.Path]::GetFullPath($VendorBin)
        if ($ResolvedFfmpegBin.Equals($ResolvedVendorBin, [StringComparison]::OrdinalIgnoreCase)) {
            throw "-FfmpegBin cannot be the package vendor destination: $ResolvedVendorBin"
        }
    }

    New-Item -ItemType Directory -Force -Path $VendorBin | Out-Null
    Get-ChildItem -LiteralPath $VendorBin -File -ErrorAction SilentlyContinue | Remove-Item -Force
    $VendorMetadataRoot = Split-Path $VendorBin -Parent
    $MetadataNames = @("LICENSE.txt", "SOURCE_INFO.txt", "LEGAL_INFO.json") + $RequiredMetadataNames
    foreach ($Metadata in $MetadataNames) {
        $StaleMetadata = Join-Path $VendorMetadataRoot $Metadata
        if (Test-Path -LiteralPath $StaleMetadata) {
            Remove-Item -LiteralPath $StaleMetadata -Force
        }
    }
    if ($ResolvedFfmpegBin) {
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
        foreach ($Metadata in $MetadataNames) {
            $Source = Join-Path $FfmpegRoot $Metadata
            $Destination = Join-Path $VendorMetadataRoot $Metadata
            if (Test-Path -LiteralPath $Source) {
                Copy-Item -LiteralPath $Source -Destination $Destination -Force
            }
            elseif ($Metadata -in $RequiredMetadataNames) {
                throw "Required dependency license metadata was not found beside -FfmpegBin: $Metadata"
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
    $LegalInfo = [ordered]@{
        schema_version = 1
        application_version = $Version
        application_license = "Apache-2.0"
        application_license_sha256 = $ApplicationLicenseSha256
        ffmpeg_effective_license = "GPL-covered (FFTW3 statically incorporated through Chromaprint)"
        corresponding_source_url = $(if ($CorrespondingSourceUrl) { $CorrespondingSourceUrl } else { $null })
        corresponding_source_sha256 = $(if ($CorrespondingSourceSha256) { $CorrespondingSourceSha256 } else { $null })
    }
    $LegalInfo | ConvertTo-Json -Depth 3 | Set-Content `
        -LiteralPath (Join-Path (Split-Path $VendorBin -Parent) "LEGAL_INFO.json") `
        -Encoding UTF8

    & uv.exe run --with "pyinstaller==6.16.0" pyinstaller --noconfirm --clean `
        (Join-Path $PSScriptRoot "splicr.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
    Copy-Item -LiteralPath $ApplicationLicense -Destination (Join-Path $Portable "LICENSE.txt") -Force

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

    $Artifacts = @(
        Get-Item -LiteralPath $PortableZip
        if (-not $SkipInstaller) {
            Get-Item -LiteralPath (
                Join-Path $Dist "SPLICR-Studio-$Version-Windows-x64-setup.exe"
            )
        }
    )
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
