[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Fetcher = Join-Path $PSScriptRoot "fetch_ffmpeg_release.py"
$Manifest = Join-Path $PSScriptRoot "ffmpeg-packaged-license-files.tsv"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}
$WorkRoot = Join-Path ([IO.Path]::GetTempPath()) ("splicr-fetch-ffmpeg-test-" + [guid]::NewGuid().ToString("N"))
$UnsafeManifest = Join-Path $WorkRoot "unsafe-packaged-tag.tsv"
$UnsafeNamedManifest = Join-Path $WorkRoot "unsafe-packaged-named-tag.tsv"
$UnsafeSvnManifest = Join-Path $WorkRoot "unsafe-packaged-svn-revision.tsv"
$UnsafeEncodingManifest = Join-Path $WorkRoot "unsafe-packaged-content-encoding.tsv"

try {
    New-Item -ItemType Directory -Path $WorkRoot | Out-Null
    & $Python $Fetcher --validate-manifest-only | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The default packaged-license manifest failed validation."
    }
    & $Python $Fetcher --packaged-license-manifest $Manifest --validate-manifest-only | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The explicit packaged-license manifest failed validation."
    }

    $ManifestText = [IO.File]::ReadAllText($Manifest)
    $UnsafeManifestText = $ManifestText.Replace("`tv4.2.0`t", "`tv4.2.0;unsafe`t")
    if ($UnsafeManifestText -eq $ManifestText) {
        throw "The packaged-license manifest no longer contains the release-tag fixture."
    }
    [IO.File]::WriteAllText($UnsafeManifest, $UnsafeManifestText)

    $RejectedUnsafeTag = $false
    try {
        & $Python $Fetcher --packaged-license-manifest $UnsafeManifest --validate-manifest-only 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Rejected unsafe release tag."
        }
    }
    catch {
        $RejectedUnsafeTag = $true
    }
    if (-not $RejectedUnsafeTag) {
        throw "PowerShell fetcher accepted an unsafe packaged license release tag."
    }

    $UnsafeNamedManifestText = $ManifestText.Replace(
        "`topenssl-3.6.4`t",
        "`topenssl-3.6.4;unsafe`t"
    )
    if ($UnsafeNamedManifestText -eq $ManifestText) {
        throw "The packaged-license manifest no longer contains the OpenSSL tag fixture."
    }
    [IO.File]::WriteAllText($UnsafeNamedManifest, $UnsafeNamedManifestText)

    $RejectedUnsafeNamedTag = $false
    try {
        & $Python $Fetcher --packaged-license-manifest $UnsafeNamedManifest --validate-manifest-only 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Rejected unsafe OpenSSL release tag."
        }
    }
    catch {
        $RejectedUnsafeNamedTag = $true
    }
    if (-not $RejectedUnsafeNamedTag) {
        throw "PowerShell fetcher accepted an unsafe OpenSSL release tag."
    }

    $UnsafeSvnManifestText = $ManifestText.Replace("`t6835`t", "`t6835;unsafe`t")
    if ($UnsafeSvnManifestText -eq $ManifestText) {
        throw "The packaged-license manifest no longer contains the numeric SVN revision fixture."
    }
    [IO.File]::WriteAllText($UnsafeSvnManifest, $UnsafeSvnManifestText)

    $RejectedUnsafeSvnRevision = $false
    try {
        & $Python $Fetcher --packaged-license-manifest $UnsafeSvnManifest --validate-manifest-only 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Rejected unsafe SVN revision."
        }
    }
    catch {
        $RejectedUnsafeSvnRevision = $true
    }
    if (-not $RejectedUnsafeSvnRevision) {
        throw "PowerShell fetcher accepted an unsafe packaged-license SVN revision."
    }

    $UnsafeEncodingManifestText = $ManifestText.Replace("`tbase64", "`trot13")
    if ($UnsafeEncodingManifestText -eq $ManifestText) {
        throw "The packaged-license manifest no longer contains the transport-encoding fixture."
    }
    [IO.File]::WriteAllText($UnsafeEncodingManifest, $UnsafeEncodingManifestText)

    $RejectedUnsafeEncoding = $false
    try {
        & $Python $Fetcher --packaged-license-manifest $UnsafeEncodingManifest --validate-manifest-only 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Rejected unsafe transport encoding."
        }
    }
    catch {
        $RejectedUnsafeEncoding = $true
    }
    if (-not $RejectedUnsafeEncoding) {
        throw "PowerShell fetcher accepted an unsafe packaged-license transport encoding."
    }

    Write-Output "FFmpeg packaged-license fetch validation passed tracked and negative cases."
}
finally {
    if (Test-Path -LiteralPath $WorkRoot) {
        Remove-Item -LiteralPath $WorkRoot -Recurse -Force
    }
}
