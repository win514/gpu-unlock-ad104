#Requires -RunAsAdministrator
<#
Deploy the re-packaged UEFI app to the internal EFI System Partition so no USB
stick is required.

  right-click -> Run as administrator, or:
  powershell -ExecutionPolicy Bypass -File tools\esp_deploy.ps1 -Mode diag

Only creates <esp>\EFI\GU\GU.EFI and (unlock mode) <esp>\GU-PROFILE\ASSETS.
It never touches \EFI\Microsoft, bootmgfw.efi or the default boot order.
#>
[CmdletBinding()]
param(
    [ValidateSet('diag', 'unlock')][string]$Mode = 'diag',
    [string]$Root = '',
    [switch]$RegisterBootEntry,
    # Also drop a UEFI Shell at \EFI\Shell\Shell.efi, for boards whose boot menu
    # only offers "Launch EFI Shell from filesystem device".
    [switch]$WithShell,
    # Deploy the unattended build (starts the transaction after a countdown).
    [switch]$Auto,
    # Make GU-DIAG the first entry in the firmware boot order (runs every boot).
    [switch]$SetDefault
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

# Drop any drive-letter access path this partition already carries (stale mount
# from an earlier failed run, or a letter mountvol left behind).
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

function Get-FreeBytes([string]$letter) {
    try {
        $di = [System.IO.DriveInfo]::new("${letter}:\")
        return @{ Free = $di.AvailableFreeSpace; Total = $di.TotalSize }
    }
    catch {
        $ld = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='${letter}:'" -ErrorAction SilentlyContinue
        if ($ld) { return @{ Free = [int64]$ld.FreeSpace; Total = [int64]$ld.Size } }
        return $null
    }
}

$esp = Get-EspPartition
if (-not $esp) { throw 'EFI System Partition not found (is this a UEFI/GPT system?).' }

$buildTag = if ($Mode -eq 'unlock' -and $Auto) { 'unlock-auto' } else { $Mode }
$source = Join-Path $Root "port\build\$buildTag\EFI\BOOT\BOOTX64.EFI"
if (-not (Test-Path $source)) { throw "Missing build: $source (run port\build.py first)." }

Clear-EspAccessPaths $esp
$letter = Mount-Esp $esp
Write-Host "ESP: disk $($esp.DiskNumber) partition $($esp.PartitionNumber) mounted at ${letter}:"

try {
    $space = Get-FreeBytes $letter
    if ($space) {
        Write-Host ("Free space on ESP: {0:N0} MB / {1:N0} MB" -f ($space.Free / 1MB), ($space.Total / 1MB))
    }
    else {
        Write-Host 'Free-space query failed; skipping the pre-copy space check.'
    }

    $targetDir = Join-Path "${letter}:\" 'EFI\GU'
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    Copy-Item $source (Join-Path $targetDir 'GU.EFI') -Force
    Write-Host "copied: $targetDir\GU.EFI ($((Get-Item $source).Length) bytes)"

    # The application writes its run directory here; pre-create it so an older
    # image that does not create it itself still works.
    $runRoot = Join-Path "${letter}:\" 'GU-PROFILE'
    New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
    Write-Host "run root: $runRoot"

    if ($Mode -eq 'unlock') {
        $assets = Join-Path $Root 'build\assets'
        $names = 'booter_load_ad102.bin', 'v67-ad102-610.43.03-four-plm.bin', 'gsp_ga10x.bin', 'gsp_boot_ad102.bin', 'gsp_boot_desc_ad102.bin'
        $need = (Get-ChildItem $assets -File | Where-Object { $names -contains $_.Name } | Measure-Object Length -Sum).Sum
        if ($space -and $space.Free -lt $need) {
            throw ("ESP needs {0:N0} MB for the firmware assets but only {1:N0} MB is free." -f ($need / 1MB), ($space.Free / 1MB))
        }
        $assetDir = Join-Path "${letter}:\" 'GU-PROFILE\ASSETS'
        New-Item -ItemType Directory -Force -Path $assetDir | Out-Null
        foreach ($name in $names) {
            Copy-Item (Join-Path $assets $name) (Join-Path $assetDir $name) -Force
            Write-Host "asset: $name"
        }
    }

    if ($WithShell) {
        $shell = Join-Path $Root 'build\shell\Shell.efi'
        if (-not (Test-Path $shell)) { throw "Missing UEFI Shell binary: $shell" }
        $shellDir = Join-Path "${letter}:\" 'EFI\Shell'
        New-Item -ItemType Directory -Force -Path $shellDir | Out-Null
        Copy-Item $shell (Join-Path $shellDir 'Shell.efi') -Force
        Copy-Item $shell (Join-Path "${letter}:\" 'shellx64.efi') -Force
        Write-Host "shell: $shellDir\Shell.efi and \shellx64.efi"
    }

    $efiSha = (Get-FileHash (Join-Path $targetDir 'GU.EFI') -Algorithm SHA256).Hash.ToLower()
    Write-Host "sha256: $efiSha"
}
finally {
    Unmount-Esp $esp $letter
    Write-Host "unmounted ${letter}:"
}

if ($RegisterBootEntry) {
    # drop stale entries first so repeated deploys never stack duplicates
    $stale = @(Get-FirmwareEntries)
    if ($stale.Count -gt 0) { Remove-GuDiagEntries | Out-Null }
    $copy = cmd /c "bcdedit /copy {bootmgr} /d GU-DIAG" 2>&1 | Out-String
    $m = [regex]::Match($copy, '\{[0-9a-fA-F-]{36}\}')
    if (-not $m.Success) { throw "bcdedit /copy failed: $copy" }
    $guid = $m.Value
    cmd /c "bcdedit /set $guid path \EFI\GU\GU.EFI" | Out-Null
    Write-Host "NVRAM boot entry created: GU-DIAG -> \EFI\GU\GU.EFI ($guid)"
    Write-Host "remove it later with: cmd /c \"bcdedit /delete $guid\""
    if ($SetDefault) {
        cmd /c "bcdedit /set {fwbootmgr} displayorder $guid /addfirst" | Out-Null
        Write-Host 'GU-DIAG is now the first firmware boot entry (runs on every power-on).'
        Write-Host 'restore Windows first with: bcdedit /set {fwbootmgr} displayorder {current} /addfirst'
    }
}

Write-Host ''
Write-Host 'NEXT (manual, in this order):'
Write-Host '  1. Reboot, enter BIOS (Del or F2), disable Secure Boot, save and exit.'
Write-Host '  2. Open the boot menu (F8) and choose one of:'
Write-Host '       - "GU-DIAG"            (if -RegisterBootEntry was used), or'
Write-Host '       - "Boot From File"     -> EFI -> GU -> GU.EFI, or'
Write-Host '       - "Launch EFI Shell"   -> fs0:\EFI\GU\GU.EFI  (if -WithShell was used)'
Write-Host '  3. The read-only pass runs, writes GU-PROFILE\RUNnn\PROFILE.TXT'
Write-Host '     and cold-reboots to Windows by itself.'
Write-Host '  4. Back in Windows, run tools\esp_recover.ps1 -Cleanup'
