[CmdletBinding()]
param(
    [string]$GraphDirectory = (Join-Path $PSScriptRoot "ffmpeg-source-graph")
)

$ErrorActionPreference = "Stop"
$GraphDirectory = [IO.Path]::GetFullPath($GraphDirectory)
$Lock = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "ffmpeg-source-lock.json") | ConvertFrom-Json

function Assert-Condition([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw $Message
    }
}

$StagesPath = Join-Path $GraphDirectory "enabled-stages.txt"
$RevisionsPath = Join-Path $GraphDirectory "source-revisions.tsv"
$CommandsPath = Join-Path $GraphDirectory "source-commands.txt"
$InfoPath = Join-Path $GraphDirectory "GRAPH_INFO.txt"
foreach ($Path in @($StagesPath, $RevisionsPath, $CommandsPath, $InfoPath)) {
    Assert-Condition (Test-Path -LiteralPath $Path -PathType Leaf) "Missing source graph file: $Path"
}

$Stages = @(Get-Content -LiteralPath $StagesPath | Where-Object { $_.Trim() })
Assert-Condition ($Stages.Count -eq $Lock.dependency_graph.enabled_stage_count) `
    "Expected $($Lock.dependency_graph.enabled_stage_count) enabled stages, found $($Stages.Count)"
Assert-Condition (@($Stages | Sort-Object -Unique).Count -eq $Stages.Count) `
    "Enabled source graph contains duplicate stages"
Assert-Condition ($Stages -contains "scripts.d/50-openh264.sh") "OpenH264 stage is missing"
Assert-Condition ($Stages -notcontains "scripts.d/50-x264.sh") "GPL libx264 stage must not be enabled"
Assert-Condition ($Stages -notcontains "scripts.d/50-x265.sh") "GPL libx265 stage must not be enabled"

$RevisionText = Get-Content -Raw -LiteralPath $RevisionsPath
$RevisionRows = @(Import-Csv -LiteralPath $RevisionsPath -Delimiter "`t")
Assert-Condition ($RevisionRows.Count -eq $Lock.dependency_graph.source_locator_count) `
    "Expected $($Lock.dependency_graph.source_locator_count) source locators, found $($RevisionRows.Count)"
Assert-Condition (-not @($RevisionRows | Where-Object { -not $_.locator -or -not $_.revision })) `
    "Every enabled source locator must have an exact commit/tag/revision"
Assert-Condition ($RevisionText.Contains(
    "https://github.com/cisco/openh264.git",
    [StringComparison]::Ordinal
)) "OpenH264 repository is missing from the source revision graph"
Assert-Condition ($RevisionText.Contains(
    "8b2d28faade10d74d99ac80e199aef664c9c5a3b",
    [StringComparison]::Ordinal
)) "Pinned OpenH264 revision is missing from the source revision graph"
Assert-Condition ($RevisionText.Contains("SCRIPT_REV`t6835", [StringComparison]::Ordinal)) `
    "Pinned LAME SVN revision is missing from the source revision graph"

$CommandText = Get-Content -Raw -LiteralPath $CommandsPath
foreach ($Stage in $Stages) {
    Assert-Condition ($CommandText.Contains("### $Stage", [StringComparison]::Ordinal)) `
        "Source fetch commands are missing enabled stage: $Stage"
}

$Info = Get-Content -Raw -LiteralPath $InfoPath
foreach ($Token in @(
    "Target: $($Lock.binary.target)",
    "Variant: $($Lock.binary.variant)",
    "Add-in: $($Lock.binary.addin)",
    "Enabled stage count: $($Lock.dependency_graph.enabled_stage_count)"
)) {
    Assert-Condition ($Info.Contains($Token, [StringComparison]::Ordinal)) `
        "Source graph info is missing: $Token"
}

Write-Output "FFmpeg enabled source graph passed ($($Stages.Count) stages)."
