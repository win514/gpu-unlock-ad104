#Requires -Version 5.1
<#
Build the tensor issue-rate probe with the CUDA toolkit.

  powershell -ExecutionPolicy Bypass -File tools\build_bench.ps1
  powershell -ExecutionPolicy Bypass -File tools\build_bench.ps1 -Arch sm_89

Needs nvcc on PATH, or a CUDA toolkit installed under the default location.
The probe is a standalone executable; it does not need Visual Studio, Python or
WSL. Only the CUDA Toolkit's compiler + runtime components are required.
#>
[CmdletBinding()]
param(
    [string]$Arch = 'sm_89',
    [string]$CudaRoot = 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$src = Join-Path $repo 'bench\mma_bench.cu'
$outDir = Join-Path $repo 'build\bench'
$exe = Join-Path $outDir 'mma_bench.exe'

if (-not (Test-Path $src)) { throw "missing benchmark source: $src" }

function Find-Nvcc {
    $cmd = Get-Command nvcc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    if (Test-Path $CudaRoot) {
        $candidate = Get-ChildItem $CudaRoot -Directory |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName 'bin\nvcc.exe' } |
            Where-Object { Test-Path $_ } |
            Select-Object -First 1
        if ($candidate) { return $candidate }
    }
    return $null
}

$nvcc = Find-Nvcc
if (-not $nvcc) {
    Write-Host 'nvcc not found.' -ForegroundColor Yellow
    Write-Host 'Install the CUDA Toolkit (Windows, "exe (network)" installer,'
    Write-Host 'select at least "CUDA Runtime" and "CUDA Compiler"), then re-run.'
    Write-Host 'https://developer.nvidia.com/cuda-downloads'
    return 1
}

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
function Find-VcVars {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path $vswhere) {
        $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
        if ($vs) {
            $bat = Join-Path $vs.Trim() 'VC\Auxiliary\Build\vcvars64.bat'
            if (Test-Path $bat) { return $bat }
        }
    }
    foreach ($edition in 'Community', 'Professional', 'Enterprise', 'BuildTools') {
        $bat = Join-Path $env:ProgramFiles "Microsoft Visual Studio\2022\$edition\VC\Auxiliary\Build\vcvars64.bat"
        if (Test-Path $bat) { return $bat }
    }
    return $null
}

$archArg = "-arch=$Arch"
Write-Host "nvcc : $nvcc"
Write-Host "arch : $Arch"
Write-Host "out  : $exe"

# nvcc shells out to cl.exe, which only exists inside a developer environment.
$vcvars = Find-VcVars
if ($vcvars) {
    Write-Host "vc   : $vcvars"
    $inner = "call `"$vcvars`" >nul 2>&1 && `"$nvcc`" $archArg -O3 -std=c++17 --expt-relaxed-constexpr -o `"$exe`" `"$src`""
    cmd /c $inner
} else {
    Write-Host 'vc   : vcvars64.bat not found; trying nvcc with the current PATH'
    & $nvcc $archArg -O3 -std=c++17 --expt-relaxed-constexpr -o $exe $src
}
if ($LASTEXITCODE -ne 0) { throw "nvcc failed with exit code $LASTEXITCODE" }

$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
Write-Host "built: $exe ($((Get-Item $exe).Length) bytes)"
Write-Host "sha256: $hash"
Write-Host ''
Write-Host 'Next: tools\bench_run.ps1  (records one state; run it once unlocked'
Write-Host '      and once stock, then compare the two JSON files)'
return 0
