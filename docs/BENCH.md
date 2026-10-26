# Measuring the gain

The unlock only changes the **tensor issue rate**: `HMMA`/`IMMA` instructions
(the `mma.sync` family) go from half rate to full rate. Nothing else in the GPU
moves — clocks, memory bandwidth, FP32 CUDA cores, video engines are untouched.

That has two consequences:

1. **No GUI tool can measure it.** GPU-Z, HWiNFO, FurMark, AIDA64's GPGPU suite
   and 3DMark all exercise the graphics pipeline or the FP32 pipes. They will
   show identical numbers before and after.
2. **You need to issue `mma.sync` yourself.** That means CUDA. There is no
   shortcut, no registry key, and no freeware probe that reports it.

This directory ships the upstream issue-rate probe, `bench/mma_bench.cu`, which
measures six modes in one run:

| mode | what it exercises | expected to change |
|---|---|---|
| `f16/f16` | HMMA, FP16 accumulate | yes (tensor) |
| **`f16/f32`** | **HMMA, FP32 accumulate** | **yes, ≈2×** |
| **`bf16/f32`** | **HMMA/BF16, FP32 accumulate** | **yes, ≈2×** |
| `s8/s32` | IMMA, integer | usually unchanged |
| `dp4a` | DP4A dot product | unchanged (control) |
| `ffma` | scalar FP32 | unchanged (control) |

The controls matter: if `ffma` or `dp4a` also move, your measurement is invalid
(clocks or power limit changed), not a real gain.

---

## 1. Install the CUDA toolkit

Download from <https://developer.nvidia.com/cuda-downloads> — Windows, x86_64,
`exe (network)`.

In the installer choose **Custom**, and select only:

- **CUDA Runtime**
- **CUDA Compiler** (`nvcc`)

Skip Visual Studio integration, Nsight, samples and the bundled driver. That is
roughly 1.5–2 GB instead of 3–6 GB. No restart is needed.

CUDA 12.x supports `sm_89` (Ada) and works with the 616.56 driver.

## 2. Build the probe

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_bench.ps1
```

Output: `build\bench\mma_bench.exe`, built for `sm_89`. The script prints the
binary's SHA-256 — keep it, both measurements must use the same binary.

## 3. Record the unlocked state

If the machine is currently unlocked (the last power-on went through `GU-DIAG`
and reached `FINAL status=0 clean=1`):

```powershell
powershell -ExecutionPolicy Bypass -File tools\bench_run.ps1 -Label unlocked
```

## 4. Record the stock state

Power off, power on, and at the boot menu press **F8**, then pick
**Windows Boot Manager** — this bypasses `GU-DIAG`, so the card stays stock.

```powershell
powershell -ExecutionPolicy Bypass -File tools\bench_run.ps1 -Label stock
```

## 5. Compare

```powershell
powershell -ExecutionPolicy Bypass -File tools\bench_run.ps1 -Compare
```

```
mode          unlocked      stock    ratio
------------------------------------------
f16/f16          330.2      165.4     2.00  <-- tensor
f16/f32          331.6      165.6     2.00  <-- tensor
bf16/f32         330.6      165.5     2.00  <-- tensor
s8/s32           379.5      379.5     1.00
dp4a             754.8      754.8     1.00
ffma              57.3       57.3     1.00
```

(Numbers above are the shape of the upstream AD102 result, not a prediction for
your card.)

What counts as success:

- `f16/f32` and `bf16/f32` ratio **≥ 1.8** → unlock is working
- ratio **1.0** → the selectors did not stick; check the report for
  `SELECTOR RESULT ... matched=1`
- ratio **1.2–1.5** → clock or power-limited run; repeat with the GPU idle and
  the same power cap
- `dp4a`/`ffma`/`s8` ratio outside 0.9–1.1 → measurement invalid

## 6. Conditions for a fair comparison

- Same power limit (`nvidia-smi --query-gpu=power.limit`), same driver, same
  binary, same `iters`/`reps`
- GPU otherwise idle, display attached, no other CUDA process
- Run each state at least twice; `bench_run.ps1` already does 3 repetitions and
  keeps the best
- Ambient temperature matters at the power wall — if the second run is much
  hotter, the comparison is biased

## 7. A more realistic (but smaller) number

`bench/mma_bench.cu` measures **register-resident issue rate**, i.e. the
architecture limit. Real libraries are bandwidth- and shape-bound, so expect
much less in practice. The upstream matched cuBLAS runs measured:

- RTX 4090: FP16 GEMM +12–34 % by shape, BF16 +16–20 %
- RTX 4070 Ti AD104: cuBLAS 4096² FP16 +80.1 %, BF16 +76.4 % (single cold run)

If you want that number too, `bench/validate_gemm.cu` builds a cuBLAS GEMM
harness:

```powershell
nvcc -arch=sm_89 -O3 -std=c++17 -lcublas -o build\bench\validate_gemm.exe bench\validate_gemm.cu
```

Run it in both states and compare the medians. Treat it as an application-level
indicator, not a guarantee.

## 8. If you would rather not install CUDA

Then the evidence stays at the register level: `SS0 = 0x88888888`,
`SS1 = 0x8`, `EFFECTIVE = 0` read back after FLR and again just before Windows
starts. That proves the mechanism engaged; it does not prove a throughput gain.
State that limitation explicitly when publishing results.
