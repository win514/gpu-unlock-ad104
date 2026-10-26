#Requires -RunAsAdministrator
<#
Collect the PROFILE.TXT produced by the diag build from the internal ESP and
(optionally) remove everything this toolchain put there.

  powershell -ExecutionPolicy Bypass -File tools\esp_recover.ps1
  powershell -ExecutionPolicy Bypass -File tools\esp_recover.ps1 -Cleanup
#>
[CmdletBinding()]
param(
    [string]$Root = '',
    [switch]$Cleanup
)

$ErrorActionPreference = 'Stop'

if (-not $Root) { $Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path }

# bcdedit output is localised (the field name is not always "identifier") and
# PowerShell treats {guid} as a script block, so every call goes through cmd /c
# and GUIDs are found by regex inside the entry block.
function Get-FirmwareEntries {
    $lines = @(cmd /c "bcdedit /enum firmware")
    $entries = @()
    $current = $null
    foreach ($line in $lines) {
        if ($line -match '(\{[0-9a-fA-F-]{36}\})') {
            $current = $Matches[1]
        }
        if ($line -match 'description\s+GU-DIAG' -and $current) {
            $entries += $current
        }
    }
    return $entries
}

function Remove-GuDiagEntries {
    $ids = @(Get-FirmwareEntries)
    foreach ($id in $ids) {
        Write-Host "removing firmware entry $id"
        cmd /c "bcdedit /delete $id" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            cmd /c "bcdedit /delete $id /cleanup" | Out-Null
        }
    }
    return $ids.Count
}

function Get-EspPartition {
    Get-Partition | Where-Object { $_.GptType -eq '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}' } |
        Select-Object -First 1
}

function Get-FreeLetter {
    $used = [System.IO.DriveInfo]::GetDrives() | ForEach-Object { $_.Name.Substring(0, 1) }
    $used += (Get-PSDrive -PSProvider FileSystem).Name
    foreach ($c in 'Z', 'Y', 'X', 'W', 'V', 'U', 'T', 'S') {
        if ($used -notcontains $c) { return $c }
    }
    throw 'No free drive letter for the ESP mount.'
}

function Clear-EspAccessPaths($part) {
    $current = Get-Partition -DiskNumber $part.DiskNumber -PartitionNumber $part.PartitionNumber
    foreach ($ap in $current.AccessPaths) {
        if ($ap -match '^[A-Za-z]:\\$') {
            Write-Host "clearing stale access path $ap"
            Remove-PartitionAccessPath -DiskNumber $part.DiskNumber -PartitionNumber $part.PartitionNumber -AccessPath $ap -ErrorAction SilentlyContinue
        }
    }
}

function Mount-Esp($part) {
    $letter = Get-FreeLetter
    $access = "${letter}:\"
    try {
        Add-PartitionAccessPath -DiskNumber $part.DiskNumber -PartitionNumber $part.PartitionNumber -AccessPath $access -ErrorAction Stop
    }
    catch {
        Write-Host "Add-PartitionAccessPath failed ($($_.Exception.Message)); falling back to mountvol"
        mountvol "${letter}:" /S | Out-Null
    }
    for ($i = 0; $i -lt 40; $i++) {
        if (Test-Path $access) { return $letter }
        Start-Sleep -Milliseconds 250
    }
    throw "ESP did not become accessible at $access"
}

function Unmount-Esp($part, [string]$letter) {
    $access = "${letter}:\"
    try {
        Remove-PartitionAccessPath -DiskNumber $part.DiskNumber -PartitionNumber $part.PartitionNumber -AccessPath $access -ErrorAction Stop
    }
    catch {
        mountvol "${letter}:" /D 2>$null | Out-Null
    }
}

$esp = Get-EspPartition
if (-not $esp) { throw 'EFI System Partition not found.' }

$outDir = Join-Path $Root 'out\GU-PROFILE'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$found = $null
Clear-EspAccessPaths $esp
$letter = Mount-Esp $esp
try {
    $runRoot = Join-Path "${letter}:\" 'GU-PROFILE'
    $runs = @(Get-ChildItem $runRoot -Directory -Filter 'RUN*' -ErrorAction SilentlyContinue | Sort-Object Name)
    if ($runs.Count -eq 0) {
        Write-Host 'No GU-PROFILE\RUNnn directory on the ESP - the build did not run yet.'
    }
    else {
        # Copy every run: unlock runs write REPORT.TXT only, diag runs also
        # write PROFILE.TXT, and the interesting one is not always the latest.
        foreach ($run in $runs) {
            foreach ($f in 'PROFILE.TXT', 'REPORT.TXT') {
                $src = Join-Path $run.FullName $f
                if (-not (Test-Path $src)) { continue }
                $dst = Join-Path $outDir "$($run.Name)-$f"
                Copy-Item $src $dst -Force
                Write-Host "copied: $dst ($((Get-Item $dst).Length) bytes)"
                if ($f -eq 'PROFILE.TXT') { $found = $dst }
            }
        }
        $latest = $runs[-1]
        $lastReport = Join-Path $outDir "$($latest.Name)-REPORT.TXT"
        if (Test-Path $lastReport) {
            Write-Host ''
            Write-Host "last stage/final lines of $($latest.Name):"
            Get-Content $lastReport | Select-String -Pattern 'CHECK stage=|FINAL status=|READY:|unlock failed|STOP:|transaction result=' |
                Select-Object -Last 8 | ForEach-Object { "  $($_.Line.Trim())" }
        }
    }

    if ($Cleanup) {
        foreach ($p in 'EFI\GU', 'GU-PROFILE') {
            $full = Join-Path "${letter}:\" $p
            if (Test-Path $full) { Remove-Item $full -Recurse -Force; Write-Host "removed: \$p" }
        }
    }
}
finally {
    Unmount-Esp $esp $letter
    Write-Host "unmounted ${letter}:"
}

if ($Cleanup) {
    $removed = Remove-GuDiagEntries
    if ($removed -gt 0) { Write-Host "removed $removed NVRAM boot entry(ies)" }
    else { Write-Host 'no GU-DIAG firmware entry present' }
    cmd /c "bcdedit /set {fwbootmgr} displayorder {current} /addfirst" | Out-Null
    Write-Host 'Windows restored as first firmware boot entry'
}

Write-Host ''
if ($found) {
    Write-Host 'NEXT:'
    Write-Host "  python tools\profile_to_header.py $found"
    Write-Host '  python port\build.py --zig tools\zig\zig-x86_64-windows-0.14.1\zig.exe --mode unlock'
}
else {
    Write-Host 'No PROFILE.TXT collected.'
}
