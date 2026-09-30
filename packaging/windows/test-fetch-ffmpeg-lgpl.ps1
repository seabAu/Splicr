[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Fetcher = Join-Path $PSScriptRoot "fetch-ffmpeg-lgpl.ps1"
$Manifest = Join-Path $PSScriptRoot "ffmpeg-packaged-license-files.tsv"
$WorkRoot = Join-Path ([IO.Path]::GetTempPath()) ("splicr-fetch-ffmpeg-test-" + [guid]::NewGuid().ToString("N"))
$UnsafeManifest = Join-Path $WorkRoot "unsafe-packaged-tag.tsv"

try {
    New-Item -ItemType Directory -Path $WorkRoot | Out-Null
    & $Fetcher -PackagedLicenseManifest $Manifest -ValidateManifestOnly | Out-Null

    $ManifestText = [IO.File]::ReadAllText($Manifest)
    $UnsafeManifestText = $ManifestText.Replace("`tv4.2.0`t", "`tv4.2.0;unsafe`t")
    if ($UnsafeManifestText -eq $ManifestText) {
        throw "The packaged-license manifest no longer contains the release-tag fixture."
    }
    [IO.File]::WriteAllText($UnsafeManifest, $UnsafeManifestText)

    $RejectedUnsafeTag = $false
    try {
        & $Fetcher -PackagedLicenseManifest $UnsafeManifest -ValidateManifestOnly | Out-Null
    }
    catch {
        $RejectedUnsafeTag = $true
    }
    if (-not $RejectedUnsafeTag) {
        throw "PowerShell fetcher accepted an unsafe packaged license release tag."
    }

    Write-Output "FFmpeg packaged-license fetch validation passed tracked and negative cases."
}
finally {
    if (Test-Path -LiteralPath $WorkRoot) {
        Remove-Item -LiteralPath $WorkRoot -Recurse -Force
    }
}
