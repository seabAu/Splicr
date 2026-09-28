[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $Source,

    [string] $Destination
)

$ErrorActionPreference = "Stop"
$sourceRoot = (Resolve-Path -LiteralPath $Source).Path
$Destination = if ($Destination) {
    $Destination
} else {
    Join-Path $PSScriptRoot "..\legacy\narrator"
}
$destinationRoot = [IO.Path]::GetFullPath($Destination)

function Get-RelativeChildPath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Parent,

        [Parameter(Mandatory = $true)]
        [string] $Child
    )

    $prefix = $Parent.TrimEnd([IO.Path]::DirectorySeparatorChar) +
        [IO.Path]::DirectorySeparatorChar
    if (-not $Child.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is not below expected parent: $Child"
    }
    return $Child.Substring($prefix.Length)
}

if (Test-Path -LiteralPath $destinationRoot) {
    throw "Destination already exists: $destinationRoot"
}

$rootFiles = @(
    "Narrator.py",
    "Start Narrator.bat",
    "Start Narrator Web.bat",
    "README.md",
    "HANDOVER.md",
    "CATALOGUE.md",
    "pyproject.toml",
    "tests_mockllm.py"
)
$sourceDirectories = @("narrator", "web", "tests", "tools")
$excludedDirectoryNames = @(
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
    ".ruff_cache",
    "webui"
)
$excludedFileExtensions = @(".pyc", ".pyo")

New-Item -ItemType Directory -Path $destinationRoot | Out-Null

foreach ($name in $rootFiles) {
    $path = Join-Path $sourceRoot $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Copy-Item -LiteralPath $path -Destination $destinationRoot
    }
}

foreach ($directoryName in $sourceDirectories) {
    $sourceDirectory = Join-Path $sourceRoot $directoryName
    if (-not (Test-Path -LiteralPath $sourceDirectory -PathType Container)) {
        throw "Expected Narrator source directory is missing: $sourceDirectory"
    }

    Get-ChildItem -LiteralPath $sourceDirectory -Recurse -File | Where-Object {
        $relativePath = Get-RelativeChildPath -Parent $sourceDirectory -Child $_.FullName
        $pathParts = $relativePath -split '[\\/]'
        $excludedParts = @(
            $pathParts |
                Select-Object -SkipLast 1 |
                Where-Object { $excludedDirectoryNames -contains $_ }
        )
        $excludedParts.Count -eq 0 -and
            $excludedFileExtensions -notcontains $_.Extension
    } | ForEach-Object {
        $relativePath = Get-RelativeChildPath -Parent $sourceDirectory -Child $_.FullName
        $targetPath = Join-Path (Join-Path $destinationRoot $directoryName) $relativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $targetPath) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $targetPath
    }
}

$files = Get-ChildItem -LiteralPath $destinationRoot -Recurse -File
$byteCount = ($files | Measure-Object -Property Length -Sum).Sum
Write-Output "Imported $($files.Count) files ($byteCount bytes) to $destinationRoot"
