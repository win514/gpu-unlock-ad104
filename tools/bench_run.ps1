#Requires -Version 5.1
<#
Record one tensor issue-rate measurement and store it as JSON.

  powershell -ExecutionPolicy Bypass -File tools\bench_run.ps1 -Label unlocked
  powershell -ExecutionPolicy Bypass -File tools\bench_run.ps1 -Label stock

Run it once with the unlock active and once from a stock power-on, then:

  powershell -ExecutionPolicy Bypass -File tools\bench_run.ps1 -Compare

The probe is register-resident: it measures ptxas issue rate for
f16/f16, f16/f32, bf16/f32, s8/s32, dp4a and ffma. Only f16/f32 and bf16/f32
are controlled by the speed-select registers; dp4a/ffma/s8 act as controls and
must NOT move between the two states.
#>
[CmdletBinding()]
param(
    [string]$Label = '',
    [int]$Iters = 20000,
    [int]$Reps = 3,
    [switch]$Compare
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$exe = Join-Path $repo 'build\bench\mma_bench.exe'
$outDir = Join-Path $repo 'build\bench\runs'
$smi = Join-Path $env:SystemRoot 'System32\nvidia-smi.exe'

if ($Compare) {
    $runs = Get-ChildItem $outDir -Filter '*.json' -ErrorAction SilentlyContinue | Sort-Object Name
    if ($runs.Count -lt 2) { throw "need at least two recordings in $outDir" }
    $sets = @{}
    foreach ($f in $runs) {
        $d = Get-Content $f.FullName -Raw | ConvertFrom-Json
        $sets[$d.label] = $d
    }
    $names = @($sets.Keys | Sort-Object)
    Write-Host ("`n{0,-10} {1,10} {2,10} {3,8}" -f 'mode', $names[0], $names[1], 'ratio')
    Write-Host ('-' * 42)
    foreach ($m in $sets[$names[0]].modes.PSObject.Properties.Name) {
        $a = $sets[$names[0]].modes.$m
        $b = $sets[$names[1]].modes.$m
        $ratio = if ($a -gt 0) { $b / $a } else { 0 }
        $mark = ''
        if ($m -match 'f16/f32|bf16/f32') { $mark = if ($ratio -gt 1.5) { '  <-- tensor' } else { '  <-- tensor (no gain?)' } }
        elseif ($ratio -gt 1.15 -or $ratio -lt 0.87) { $mark = '  <-- control moved!' }
        Write-Host ("{0,-10} {1,10:N1} {2,10:N1} {3,8:N2}{4}" -f $m, $a, $b, $ratio, $mark)
    }
    Write-Host ''
    Write-Host 'Expected: f16/f32 and bf16/f32 roughly double; dp4a/ffma/s8/s32 ~unchanged.'
    return 0
}

if (-not $Label) { throw 'pass -Label (e.g. unlocked|stock) or -Compare' }
if (-not (Test-Path $exe)) { throw "missing $exe (run tools\build_bench.ps1 first)" }

New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$gpu = & $smi --query-gpu=name,uuid,driver_version,power.limit,clocks.sm,clocks.max.sm --format=csv,noheader 2>&1
Write-Host "gpu : $gpu"

$output = & $exe $Iters $Reps 2>&1
$output | ForEach-Object { Write-Host $_ }

$modes = [ordered]@{}
foreach ($line in $output) {
    if ($line -match '^(f16/f16|f16/f32|bf16/f32|s8/s32|dp4a|ffma)\s+([0-9.]+)') {
        $modes[$Matches[1].Trim()] = [double]$Matches[2]
    }
}
if ($modes.Count -eq 0) { throw 'could not parse probe output' }

$record = [ordered]@{
    label      = $Label
    timestamp  = (Get-Date).ToString('o')
    gpu        = ($gpu | Out-String).Trim()
    iters      = $Iters
    reps       = $Reps
    modes      = $modes
    exe_sha256 = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
    raw        = ($output | Out-String)
}
$file = Join-Path $outDir ("{0}-{1}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $Label)
$record | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 $file
Write-Host "`nwrote $file"
Write-Host 'Switch state (power off -> boot stock, or boot GU-DIAG), run again with the other label, then -Compare.'
return 0
