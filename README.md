# gpu-unlock-ad104

UEFI-stage tensor-core unlock for consumer Ada **AD104** GeForce cards on Windows — no Linux install, no USB stick, no driver patch.

This repository is the engineering record of porting the AD102/AD103 unlock chain to `10de:2783` (RTX 4070 SUPER). The firmware transaction **completes correctly**. The tensor throughput **does not change**. Both statements are backed by logs in this repository, and the gap between them is the most interesting result here.

---

## 1. Status: what was achieved, what was not

### Achieved — the transaction runs end to end on AD104

```
AD102 SINGLE RESULT: booter_ret=0 halt_ret=0 all_expected=0
                     marker=0x67b00001 marker_ok=1 cpuctl=0x10 debug=0xda550000
                     WPR2=02ff8e00:02f4e000

SELECTOR RESULT: SS0 before=0x53467050 after=0x88888888 expected=0x88888888 matched=1 status=0
SELECTOR RESULT: SS1 before=0x7        after=0x8        expected=0x8        matched=1 status=0

POST-FLR  SS0=0x88888888 SS1=0x00000008
transaction result=0 containment=0 started=1 quiesced=1 fault=0 retained=0 maps=0 FLR=1
POST-GOP  SS0=0x88888888 SS1=0x00000008
FINAL status=0 stage=post-unlock-handoff attempted=1 driver_release=1 clean=1
```

Every gate passed: signed FWSEC-FRTS completed (`scratch=0`, WPR2 reserved), the signed booter accepted the crafted V67 block (`marker=0x67b00001`, SEC2 `CPUCTL=0x10` HALT, `DEBUGINFO=0xda550000`), the four protected PLM writes were issued in one SEC2 launch, the host-side selector writes read back correctly, a PCIe FLR was performed, and the selectors survived it and the pre-Windows handoff. Clean shutdown, no retained DMA.

This is the first time the AD104-350 (`10de:2783`) transaction has been executed. It had never been attempted by any of the upstream projects.

### Not achieved — no throughput gain

```
# mma_bench, on the running system, immediately after RUN03 booted Windows
NVIDIA GeForce RTX 4070 SUPER, 56 SMs, sm_89
mode       best TF/s
f16/f16        142.4
f16/f32        148.0      <- half of the 285 TF/s stock specification
bf16/f32       147.5
s8/s32         300.0
dp4a            74.2
ffma            36.1
```

Baseline on the same machine, same binary, stock power-on: `f16/f32 = 147.5`.

**Ratio = 1.00.** The write survives every observation the application can make, yet the issue rate that `mma.sync` achieves is unchanged.

The controls behaved correctly (`dp4a`, `ffma`, `s8/s32` flat within 2 %, twice), so this is not a clock, power or measurement artefact: the GPU is running at its stock power limit (220 W) and its stock clocks, and the tensor pipe is issuing at half rate.

---

## 2. Why this card did not gain, and why other cards do

### 2.1 The mechanism, precisely

The unlock does not "enable tensor cores". It clears a **feature permission** and rewrites two **speed-select** registers:

| Register | BAR0 offset | Meaning |
|---|---|---|
| `WPR_CFG` PLM | `0x1fa7cc` | write-permission mask for the WPR window |
| `FBPA` PLM | `0x9a0148` | framebuffer-page attribute permissions (observational) |
| `WPR` PLM | `0x1fa7c4` | write-permission mask for the WPR region |
| `FEAT` PLM | `0x823804` | feature permission bitmask — `0xffffff8f` means "FMLA32/IMLA2/IMLA4 restricted" |
| `SS0` | `0x82381c` | eight 4-bit speed-select fields |
| `SS1` | `0x823820` | one 4-bit field in the low nibble |
| effective readout | `0x823818` | nine 3-bit fields; `0` = nothing throttled |

The host cannot write the permission registers — direct writes are ignored. Only authenticated firmware, executing with WPR-derived privilege, can. That is why the crafted V67 signature block exists: it redirects the booter's own authenticated instructions to perform those four stores.

Once the permission is open, the host writes `SS0`/`SS1`, and the field value `8` means "full rate" in every field.

### 2.2 Cold-state comparison across chips

This is the crux. The cold `SS0` encoding is **not** the same across Ada parts:

| Device | Chip | SMs | Cold `SS0` | Cold `SS1` | Nibbles | Result |
|---|---|---:|---|---|---|---|
| `10de:2684` RTX 4090 | AD102 | 128 | `0x44023025` | `0x7` | 4,4,0,2,3,0,2,5 | **2× measured** (upstream) |
| `10de:2704` RTX 4080 | AD103 | 76 | `0x31322012` | `0x7` | 3,1,3,2,2,0,1,2 | **2× measured** (donor) |
| `10de:2705` RTX 4070 Ti SUPER | AD103 | 66 | `0x31322012` | `0x7` | 3,1,3,2,2,0,1,2 | **2× measured** (upstream) |
| `10de:2782` RTX 4070 Ti | AD104 | 60 | not published | — | — | cuBLAS FP16 **+80.1 %** (donor) |
| **`10de:2783` RTX 4070 SUPER** | **AD104-350** | **56** | **`0x53467050`** | **`0x7`** | **5,3,4,6,7,0,5,0** | **no change** |

Two observations follow immediately:

1. **AD102 and AD103 share a family resemblance** in their cold encoding (`0x44023025` vs `0x31322012`), and both respond to "all fields = 8" with a real 2× gain. The AD102 part even shows a field at value 5 (`...25`) and still works, so a non-uniform cold value is not by itself disqualifying.
2. **AD104-350 is the outlier.** Its field vector `5,3,4,6,7,0,5,0` contains a **7** — one step below the "full rate" value 8 — and a different distribution entirely. Nothing in the published analysis covers AD104-350.

The `2782` data point matters most: it is the **same die family** (AD104-400, 60 SM) and the donor's UEFI port reports a working +80 % cuBLAS gain on Windows. So "AD104 does not support this" is false. The difference is at the **SKU level**, between `AD104-400` and `AD104-350`.

### 2.3 Hypothesis A — the GSP rewrites the selectors after we leave

The static audit of `nvlddmkm.sys` (616.56) is unambiguous: the **host driver** encodes none of `SS0`, `SS1`, `EFFECTIVE`, `FEAT_PLM`, `WPR_CFG`, `WPR` or `FBPA` (see §5). It only reads the WPR2 halves, the SEC2 mailbox/CPUCTL pair and the VRAM size register.

But `nvlddmkm.sys` is not the only actor. The **GSP firmware** runs on the GPU's own RISC-V core, and it performs the speed-select programming during bring-up from data in the vBIOS. If AD104-350's GSP re-applies the vBIOS table after our FLR — after `POST-GOP`, which is the last point we can observe — the selectors would be reset to `0x53467050` while our log still shows `0x88888888`.

This would explain the exact symptom: correct at every checkpoint the application can see, wrong by the time a CUDA kernel runs.

**Discriminating test:** read `BAR0 + 0x82381C` from the running OS (RWEverything or any MMIO-capable tool). If it reads `0x53467050`, hypothesis A is confirmed.

### 2.4 Hypothesis B — `0x88888888` is not the full-rate encoding on AD104-350

The payload writes the literal `0x88888888`, i.e. "every field = 8", because that is what produced 2× on AD102 and AD103. But the field semantics are only established for those parts. On AD104-350 a field value of `8` could be:

- a reserved/invalid encoding (field ignored, hardware keeps the previous value),
- a different meaning (e.g. a divisor rather than a rate index),
- or valid for six of eight fields but not the two that matter.

Note that `SS1` went `0x7 → 0x8` and that pattern is identical across AD102/AD103/AD104 — so at least the SS1 nibble is portable. `SS0` is the open question.

**Discriminating test:** if `BAR0 + 0x82381C` still reads `0x88888888` in the running OS while throughput stays at half rate, hypothesis B is confirmed.

### 2.5 Hypothesis C — the permission write only covers three of four targets

Our log shows the same partial pattern the upstream AD102 report describes:

```
AD102 PLM initial: index=0 target=WPR_CFG value=0x4cb8f expected=0xfffff0ff
AD102 PLM initial: index=1 target=FBPA    value=0xffffff0f expected=0xffffffff
AD102 PLM initial: index=2 target=WPR     value=0x4cb8f expected=0xffffffff
AD102 PLM initial: index=3 target=FEAT    value=0xffffff8f expected=0xffffffff
AD102 PLM chain: fires=1/1 required_expected=1; FBPA mismatch is nonfatal
AD102 SINGLE RESULT: ... all_expected=0
```

`all_expected=0` because `FBPA` never moves (`0xffffff0f`), which upstream documents as non-fatal and observes on AD102 as well. `required_expected=1` means the three that matter did match. So this path behaves like AD102 here — **it is probably not the cause**, but it cannot be excluded without reading the PLM values back **after** the GSP has started, which the application cannot do.

### 2.6 Why the other cards work

Restating the comparison in mechanism terms:

| | AD102 | AD103 | AD104-400 | AD104-350 |
|---|---|---|---|---|
| Signed FWSEC runs | yes | yes | yes | **yes** |
| Crafted V67 accepted by booter | yes | yes | yes | **yes** |
| Four PLM stores issued | yes | yes | yes | **yes** |
| `SS0 = 0x88888888` accepted | yes | yes | yes | **yes** |
| Survives FLR | yes | yes | yes | **yes** |
| Survives GSP bring-up | yes | yes | yes | **no** ← |
| Issue rate doubles | **2×** | **2×** | **+80 %** | **1.00×** |

The first six rows are the transaction; the last two are the hardware's response. On AD104-350 the transaction is provably identical, and only the hardware response differs. That is the entire finding.

### 2.7 What this means for other AD104 cards

- If you have a `10de:2782` (RTX 4070 Ti, AD104-400), the donor project already reports success and this repository's pipeline should reproduce it — but re-run the profile collection first, because the ROM/PROM hashes are board-specific.
- If you have another AD104-350 board (any 4070 SUPER), expect the same result as here until one of the two hypotheses is resolved.
- Do not generalise from AD102/AD103 success to any AD104 SKU.

### 2.8 The two experiments that would settle it

Both are cheap and neither has been run:

1. **Read `SS0` from the running OS.** Distinguishes A from B in one measurement.
2. **If B: sweep the field encoding.** With the permission open, write candidate `SS0` values (`0x88888888`, `0x77777777`, `0x99999999`, per-field sweeps) and measure after each. The transaction is repeatable, so this is a bounded search.

Until one of those is done, the honest statement is: *the AD104-350 transaction is proven; its effect is not*.

---

## 3. Compatibility: what is known, what is not

Two different claims have to be kept apart, and this repository only makes the second one:

- **reported working** — reported by an upstream project, on hardware this repository has never touched. Treated as credible but unverified here.
- **verified here** — executed and measured on the single card in §1.

Nothing in this project is a guarantee for any card, including the one it was developed on.

### 3.1 Desktop Ada

| GPU | Device ID | Chip | State | Basis |
|---|---|---|---|---|
| RTX 4090 | `10de:2684` | AD102 | **reported 2×** | upstream Linux project; register table published |
| RTX 4090 D | `10de:2685` | AD102 | untested, gated behind a flag | exists in the transaction code, never run |
| RTX 4080 | `10de:2704` | AD103 | **reported 2×** | donor Windows UEFI port |
| RTX 4080 SUPER | `10de:2703` | AD103 | untested | no profile, not admitted |
| RTX 4070 Ti SUPER | `10de:2705` | AD103 | **reported 2×** | upstream Linux project |
| RTX 4070 Ti | `10de:2782` | AD104-400 | **reported +80 % cuBLAS FP16**, single cold run | donor Windows UEFI port |
| **RTX 4070 SUPER** | **`10de:2783`** | **AD104-350** | **verified: transaction completes, throughput unchanged** | **this repository** |
| RTX 4070 | `10de:2786` | AD104 | untested | no profile, not admitted |
| RTX 4060 Ti 16 GB | `10de:2805` | AD106 | **reported: selectors go full-rate, no matched throughput test** | upstream, explicitly flagged as incomplete |
| RTX 4060 Ti 8 GB | `10de:2803` | AD106 | untested | not admitted |
| RTX 4060 | `10de:2882` | AD107 | untested | not admitted |

### 3.2 Laptop and professional parts

| Class | Why it is not covered |
|---|---|
| Ada laptop GPUs (`AD106M`/`AD107M`) | different vBIOS and power topology; laptop firmware routinely re-applies its own performance tables. Nothing here has been tested on one |
| RTX 6000 Ada, L40/L40S, RTX A-series | **not applicable** — professional parts already ship with the full FP32-accumulate tensor issue rate. There is nothing to unlock |
| Modded or vendor-overclocked vBIOS | every gate pins the ROM and PROM digests; a different vBIOS is rejected by design |

### 3.3 How to read the states

| State | Meaning for you |
|---|---|
| **reported 2×** | credible, from a project that published logs; not reproduced here |
| **reported +80 %** | a single cold run with cuBLAS on one board; not an instruction-rate figure and not repeated |
| **reported: selectors only** | the selectors were observed at full rate, but throughput was never measured against stock — do not assume a gain |
| **verified, no gain** | the transaction was executed and measured here; the mechanism engaged and the issue rate did not change |
| **untested** | no data. Do not infer anything from a neighbouring SKU |

### 3.4 Grouping by mechanism, not by marketing name

The reason the table cannot be read as "AD104 works / AD104 does not":

| Group | Cold `SS0` | Observed result |
|---|---|---|
| AD102 | `0x44023025` | 2× |
| AD103 | `0x31322012` | 2× |
| AD104-400 (`2782`) | not published | +80 % cuBLAS, one run |
| **AD104-350 (`2783`)** | **`0x53467050`** | **1.00×** |

AD102 and AD103 share an encoding family and both respond. `2782` and `2783` are the **same silicon family, different SKU** — 60 SM versus 56 SM, different vBIOS — and only `2783` has been measured here. The divergence is at SKU level, and one SKU is not a family.

### 3.5 What is missing, and who could fill it

This repository would rather publish an incomplete matrix than guess. Concretely:

| Missing | Why it matters | What would settle it |
|---|---|---|
| `2783` runtime `SS0` value | distinguishes "GSP rewrites it" from "wrong encoding" (§2.3, §2.4) | one read of `BAR0 + 0x82381C` while Windows runs |
| `2782` (`10de:2782`) `PROFILE.TXT` | same die family, working result — the best control we have | run the profiler on a 4070 Ti |
| `2786`, `2703`, `2803`, `2882` profiles | untested SKUs | one profiling boot each |
| `2805` matched throughput | upstream only observed the selectors | `bench_run.ps1` in both states |
| GSP speed-select semantics for AD104-350 | the actual open question | someone familiar with GSP firmware init |

If you own one of these cards, the useful contribution is not "it works" — it is `PROFILE.TXT` plus a matched `bench_run.ps1 -Compare`. That is enough to extend §3.1 with evidence instead of inference. See [CONTRIBUTING.md](CONTRIBUTING.md).

### 3.6 An honest summary

- This project moved the state of knowledge by exactly one data point: **`10de:2783` executes the transaction and does not gain**.
- Everything above that line is inherited from projects that did the hard work first — `Zagitta/gpu-unlock`, `JustAResearcher/gpu-unlock-ada`, `TOTORONG/AD103_win_unlocker`, `WildFlash1st/cmp90hx-unlock`. Their findings are reported here, not re-derived.
- The interesting question — why a full-rate selector write is accepted and ignored on AD104-350 — is **open**, and this repository stops at the measurement rather than at a theory.

If you can read GSP firmware, or you have a 4070 Ti to compare against, §3.5 is where this project would benefit most from someone else's work.

---

## 4. What this is (and isn't)

| | |
|---|---|
| **Is** | A UEFI application that performs the stock signed-firmware permission + selector transaction before the NVIDIA driver binds, a read-only profiler that pins every board-specific fingerprint, and a reproducible build/bench pipeline |
| **Is not** | A driver patch, vBIOS flash or fuse modification. Nothing persistent is written to the card |
| **Is not** | A working performance unlock on AD104-350. The mechanism engages; the issue rate does not change |
| **Is not** | Secure Boot compatible — the image is unsigned |

---

## 5. Why the driver is not patched

`nvlddmkm.sys` 616.56 was statically audited: absolute 32-bit immediates equal to every transaction register offset were searched across the whole image, and each hit was disassembled with backward alignment to real instruction boundaries.

| register | offset | code references | verdict |
|---|---:|---:|---|
| VRAM size | `0x1183a4` | 1 | read, `<< 0x14` to bytes |
| WPR2 low / high | `0x1fa824` / `0x1fa828` | 3 / 4 | read + `cmp 0x10` |
| SEC2 mailbox0 | `0x840040` | 2 | read + `cmp 0xc001cafe` |
| SEC2 CPUCTL | `0x840100` | 2 | read |
| `SS0`, `SS1`, `EFFECTIVE`, `FEAT_PLM`, `WPR_CFG`, `WPR`, `FBPA` | — | **0** | **no instruction encodes them** |

So the display driver cannot undo the unlock, and no policy gate needs bypassing. If hypothesis A is correct, the rewrite happens in **GSP firmware**, not in this driver — which is precisely why the audit had to be extended beyond the host-side binary to explain the null result.

A patch framework (VA → file offset → byte replacement → PE checksum, with Authenticode/test-signing constraints) was built during the investigation; the exact substitutions applied to the donor sources are kept as an auditable record in [docs/applied-patches.py](docs/applied-patches.py). Driver patching is deliberately **not** part of the unlock path.

---

## 6. Architecture

```
host: claim cold card, save PCI state, allocate DMA
  ↓
board ROM: signed FWSEC-FRTS on the GSP Falcon        (reserves WPR2)
  ↓
SEC2: unsigned-code-free execution — the unchanged signed AD102 booter
      consumes a crafted V67 signature block that redirects its own
      authenticated instructions to perform:
        WPR_CFG → FBPA → WPR → FEAT   (four protected stores)
      then writes mailbox 0x67b00001 and halts
  ↓
host: require marker + HALT + permission readbacks + PCI/BAR access
  ↓
host: SS0 = 0x88888888, SS1 = 0x8; verify nine speed-select fields read 0
  ↓
host: one PCIe FLR; verify FEAT/selector state survived; restore PCI state
  ↓
stock NVIDIA driver binds; GSP starts
```

**No decrypted firmware is distributed or required.** SEC2 authenticates and decrypts the booter internally; the crafted data only steers control flow through instructions that are already inside the authenticated image. The payload is therefore data, not code:

- 64 000 bytes of repeated canary dword `0x0000019c`
- 27 patched dwords at `0x1100` and `0xf948…0xf9fc`
- `tools/gen_payload.py` re-derives it from the documented structure and asserts byte equality with the released payload

Register map, gadget addresses and the DMEM/file-offset distinction: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 7. The two upstream bugs that blocked every non-GA102 card

Both are in the vendored transaction code and both fail **before anything is written**:

```c
/* vendor/unlock_610.c */
#ifndef GU_TARGET_PCI_ID
#define GU_TARGET_PCI_ID 0x220410deU      /* GA102 / RTX 3090 */
#endif

if (read_bar(work, 0, &chip) || chip != 0x193000a1u)   /* AD103 only */
        return GU_RESULT(-ENODEV);
```

On any Ada card the host-side identity check returns `-ENODEV` at the first readback. The module then reports `STOP: cleanup cannot be proven` and demands a power cycle, which reads like unsupported hardware but is a hard-coded constant. A third defect made it worse: a failed GOP reconnect after the transaction was treated as an unclean shutdown, so the halt-and-power-off (which erases the selectors just written) was triggered *after* a successful unlock.

All three are fixed in this tree; see §8 phase 5.

---

## 8. Investigation log

Chronological, with the evidence that changed the direction at each step. This is the part that is normally missing from write-ups.

### Phase 0 — identify the target and obtain sources

The starting artefact was a Linux kernel module (`JustAResearcher/gpu-unlock-ada`, a fork of `Zagitta/gpu-unlock`) — unusable on Windows. Three Windows-relevant projects were located:

| Project | Role |
|---|---|
| `TOTORONG/AD103_win_unlocker` (Hugging Face) | the only complete UEFI port; AD103, GPL-2.0 |
| `WildFlash1st/cmp90hx-unlock` | GA102 V67 chain (referenced, not vendored) |
| upstream 4090/2705 reports | register tables, expectations, failure semantics |

`git clone` failed with `schannel: CRYPT_E_NO_REVOCATION_CHECK (0x80092012)` — the TLS revocation check cannot complete in this network. Worked around with `codeload.github.com/<repo>/zip/refs/heads/main`; Hugging Face file fetches were unaffected.

### Phase 1 — confirm the payload is understood, not just copied

`tools/gen_payload.py` independently re-derives the 64 000-byte payload from the documented structure and asserts:

- `sha256 == 44c36b2d…` (matches the released payload)
- byte-for-byte equality with the shipped file
- the four PLM targets remain in issue order

This was the checkpoint that made everything afterwards debuggable: without it, a failure inside the transaction could not be attributed to the payload.

### Phase 2 — re-package into a parameterised UEFI target

The donor hard-codes one AD103 board across five files and thirteen places. All of it moved into `board_profile.h`; a read-only profiler (`diag.c`, `GU_DIAG_MODE`) was written to collect the real board fingerprints before any write could happen.

Design rule: **a value of 0 disables that single gate and records the observation instead**. Nothing was "relaxed to make it pass" — the pinned build re-arms every gate.

### Phase 3 — no USB stick, so boot from the internal ESP

The donor required a removable medium: `UsbPath()` accepted only `MSG_USB_DP`/`MSG_SD_DP` device-path nodes. Three separate defects surfaced here:

1. **medium check** — an internal ESP is a `MSG_HARDDRIVE_DP` node; the image refused to run at all. Fixed by accepting any volume that exposes `SimpleFileSystem` (`GU_MEDIA_STRICT=0`), with the original policy still available.
2. **`sizeof` mismatch** — `n == sizeof(HARDDRIVE_DEVICE_PATH)` never matched, because the trimmed EDK2 header pads the struct. Media detection then compares the subtype only.
3. **missing run root** — `GuIoOpen` required `\GU-PROFILE` to pre-exist and failed silently otherwise; the application printed four generic lines and exited. It now creates the directory, and every IO step logs its own status before `REPORT.TXT` exists.

`esp_deploy.ps1` / `esp_recover.ps1` were written to mount the ESP through `Add-PartitionAccessPath` (not `mountvol`, whose volume never appears to `Get-Volume` in WMI), copy the image, optionally register a firmware boot entry, and clean up.

### Phase 4 — the profiler run that produced the board profile

`diag.c` enumerates PCI, requires exactly one matching device, then reads config space, BAR0, 21 named registers, the option ROM and four PROM-view candidates, writing `PROFILE.TXT` and cold-rebooting itself.

Results that mattered:

| Field | Value | Consequence |
|---|---|---|
| BDF | `0000:02:00.0` | not `01:00.0` — the donor's hard-coded bus check would have failed |
| BAR0 | `0x8c000000`, 16 MiB | not `0x80000000` — the donor's hard-coded address would have failed |
| chip | `0x194000a1` | **AD104**, not AD103's `0x1930` |
| FEAT PLM | `0xffffff8f` | identical to AD102/AD103 cold value |
| SS0 | `0x53467050` | **different from AD103's `0x31322012`** |
| SS1 | `0x7` | identical to AD103 |
| VRAM | `0x2ffa` = 12 282 MiB | matches the 12 GB SKU |
| SEC2 CPUCTL | `0xbadf5620` | NV "bad value" sentinel; SEC2 not running, normal for a cold card |
| ROM | `0x24c00`, `55a69c17…` | board-specific VBIOS |
| PROM@0x300000 | `eb7eaa55…` (0xAA55 header) | same view offset as AD103 |

This is where AD104-350's divergence first became visible — in a field nobody had published a value for.

### Phase 5 — five defects between "compiled" and "transaction runs"

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | `CHECK stage=target status=0x8000000000000003` (`EFI_UNSUPPORTED`) | class mask compared against `0x030000` instead of `0x03000000` | literal corrected |
| 2 | `CHECK stage=cold-state status=0x6` with `SS0=0`, `SS1=0` | card not in cold state after a STOP; registers read as 0 | full AC power cycle required (protection working correctly) |
| 3 | `read_target_plm error=-19` → `STOP` | **`GU_TARGET_PCI_ID` defaulted to GA102's `0x220410de`** | follow `GU_BOARD_ID` |
| 4 | same, after fixing 3 | **`chip != 0x193000a1`** hard-coded for AD103 | follow `GU_BOARD_CHIP` |
| 5 | transaction `result=0` but `STOP: cleanup cannot be proven` | GOP did not reconnect after `ConnectController`; a missing GOP was treated as an unclean shutdown | GOP absence downgraded to a warning; selectors and PCI BAR are still verified, then Windows starts |

Defect 3 and 4 are the ones that look like "hardware unsupported". Both fire before a single register is written, and both produce a halt that requires a power cycle — which is exactly the behaviour of genuine incompatibility.

Defect 5 is subtler and worse: a **successful** transaction was being punished with the halt path, and the halt path's power-cycle recommendation erases the volatile selectors that had just been written. That is why the first successful run looked like a failure.

### Phase 6 — the clean run, and then the measurement that reversed the conclusion

RUN03: every gate green, `FINAL status=0 clean=1`, Windows started automatically, `POST-GOP SS0=0x88888888`.

Then the benchmark:

```
mode       best TF/s   (stock baseline: 147.5)
f16/f32        148.0
bf16/f32       147.5
s8/s32         300.0
dp4a            74.2
ffma            36.1
```

Ratio 1.00. Controls flat. Power limit 220 W, clocks at stock. The transaction had done everything it promised and changed nothing.

This is the result that makes the repository worth publishing: **a fully instrumented success at every observable checkpoint, and a null result at the only checkpoint that matters.**

### Phase 7 — extend the audit beyond the host driver

The null result forces the question "who else writes these registers". A static audit of `nvlddmkm.sys` established that the host driver does not (§5), which leaves the GSP firmware as the only remaining actor. That is hypothesis A in §2.3, and it is the state the investigation ended in.

### Phase 8 — rollback

ESP deployment removed, firmware boot entries deleted, Windows restored as the first boot entry, driver and vBIOS untouched. Because `SS0`/`SS1` are volatile they return to `0x53467050`/`0x7` on the first power cycle; the card has never carried a persistent modification at any point.

---

## 9. BIOS setup — do this once

Everything below is firmware-side and reversible. No BIOS setting is written by this project; you change them by hand, and you can change them back.

### 9.1 Enter the firmware setup

| Vendor | Key at power-on |
|---|---|
| ASUS (ROG / TUF / Prime) | `Del` or `F2` |
| MSI | `Del` |
| Gigabyte / AORUS | `Del` or `F2` |
| ASRock | `Del` or `F2` |
| HP / Dell / Lenovo consumer | `F10` / `F2` / `F1` |

On ASUS boards press `F7` first to leave EZ Mode — the Secure Boot entry only exists in Advanced Mode.

### 9.2 Turn Secure Boot off

The image is unsigned, so the firmware refuses to load it while Secure Boot is enabled.

| Vendor | Path |
|---|---|
| ASUS | **Boot → Secure Boot → OS Type = `Other OS`** (or `Secure Boot State = Disabled`) |
| MSI | **Settings → Security → Secure Boot → `Disabled`** |
| Gigabyte | **Boot → Secure Boot → `Disabled`** |
| ASRock | **Security → Secure Boot → `Disabled`** |

On some ASUS boards the page only shows `Setup Mode: Enabled` until the platform keys are cleared: **Boot → Secure Boot → Key Management → Clear Secure Boot keys**. That is reversible via `Restore Factory Keys` on the same page.

**How you know it took:** boot Windows and run `Confirm-SecureBootUEFI` in PowerShell. It must print `False`.

### 9.3 Turn CSM off

With the Compatibility Support Module enabled the firmware boots in legacy mode and **your EFI file will not appear in any boot menu** — the most common cause of "I cannot see GU.EFI".

| Vendor | Path |
|---|---|
| ASUS | **Boot → CSM (Compatibility Support Module) → Launch CSM = `Disabled`** |
| MSI | **Settings → Advanced → Windows OS Configuration → `UEFI`** |
| Gigabyte | **Boot → CSM Support = `Disabled`** |

On ASUS the CSM entry is sometimes hidden until **Boot → Boot Configuration → `CSM Support`** is toggled on first; that is intentional.

### 9.4 What to leave alone

- **Boot order** — untouched until you deploy. With `-SetDefault` the deploy script moves `GU-DIAG` to the front, and `esp_recover.ps1 -Cleanup` moves Windows back.
- **Fast Boot** — irrelevant; the ESP is always mounted.
- **TPM / fTPM** — unrelated to this project.
- **Above 4G decoding / Resizable BAR** — the transaction does not depend on it; BAR0 stays 16 MiB either way. Do not change it while debugging.

### 9.5 Open the boot menu

| Vendor | Boot-menu key |
|---|---|
| ASUS | `F8` |
| MSI | `F11` |
| Gigabyte / AORUS | `F12` |
| ASRock | `F11` |

Two ways to reach the image:

1. **`GU-DIAG`** — present if you deployed with `-RegisterBootEntry`. This is the reliable path; it does not depend on the firmware offering a file browser.
2. **`Boot From File`** → your ESP → `EFI` → `GU` → `GU.EFI`. Not every board has this entry, and on some it sits on the last page of the boot menu.

If neither appears: CSM is probably still on (§9.3), or the deploy did not actually write to the ESP — re-run it and check the `sha256:` line.

### 9.6 Getting back to Windows

- With `-SetDefault`: the run finishes and starts Windows by itself; nothing to press.
- Without it: `F8` → `Windows Boot Manager`.
- After a halted run (`STOP:`): hold power 10 s, unplug 30 s, power on, pick Windows.

---

## 10. The two-boot procedure

The target is **two boots**, not the dozens it took during development. The profiler therefore checks every pin-independent gate in the same pass and prints them as `PASS`/`FAIL`.

### Boot 1 — collect the profile and run every environment gate

```powershell
python tools\fetch_assets.py
python build.py --zig <zig.exe> --mode diag
powershell -ExecutionPolicy Bypass -File tools\esp_deploy.ps1 -Mode diag -RegisterBootEntry
```

Power off, power on, `F8` → `GU-DIAG`. It reads the card, writes `GU-PROFILE\RUN00\PROFILE.TXT`, and cold-reboots by itself. It never writes a register.

`PROFILE.TXT` ends with a preflight block:

```
--- preflight: pin-independent gates ---
gate class_display    = PASS
gate revision_present = PASS
gate chip_is_ad10x    = PASS
gate bar0_mapped      = PASS
gate bar0_is_16mib    = PASS
gate wpr2_released    = PASS      <- FAIL means a warm reboot was used
gate not_unlocked_yet = PASS
gate ss1_cold_like    = PASS
gate feat_plm_cold    = PASS
gate rom_readable     = PASS
info vram_encoding   = 0x2ffa (12282 MiB) - pin as GU_VRAM_MIB
--- end preflight ---
```

**If any line reads `FAIL`, fix that one thing before building the unlock image** — a `FAIL` here is exactly what would otherwise cost you a boot later:

| Gate | FAIL means | Fix |
|---|---|---|
| `wpr2_released` | the GSP still owns its window (warm reboot or a previous attempt) | shut down, unplug 30 s, retry |
| `not_unlocked_yet` | a selector field already shows full rate | already unlocked, or a stale state — power cycle |
| `bar0_is_16mib` | the aperture is not the expected size | do not build; report the value |
| `chip_is_ad10x` | not an Ada AD10x part | unsupported |
| `rom_readable` | option ROM not exposed | firmware setting; do not build |

### Boot 2 — build, deploy, execute

```powershell
powershell -ExecutionPolicy Bypass -File tools\esp_recover.ps1     # pulls PROFILE.TXT
python tools\profile_to_header.py out\GU-PROFILE\RUN00-PROFILE.TXT
python build.py --zig <zig.exe> --mode unlock --auto
powershell -ExecutionPolicy Bypass -File tools\esp_deploy.ps1 -Mode unlock -Auto -RegisterBootEntry
```

Then **shut down, unplug the power cord, wait 30 s, plug in, power on.** Press nothing. The image counts down 5 s, runs the transaction, starts Windows.

That is the whole procedure: **one profiling boot, one execution boot.**

### What still forces an extra boot, and why it is unavoidable

| Situation | Why | Cost |
|---|---|---|
| `shutdown /r` or the Windows restart menu was used | WPR2 does not reset on a warm boot; the cold-state gate refuses by design | one cold boot |
| The card was already unlocked | `not_unlocked_yet` fails | power cycle |
| GPU, vBIOS or driver was replaced | every pinned value is invalidated | re-run the profiling boot |
| A Windows update re-enabled Secure Boot | firmware refuses the unsigned image | disable it again |

Changing the board profile, pin values or assets never needs a reboot by itself — only the firmware-side events above do.

---

## 11. Build and deploy details

Full reference in [docs/BUILD.md](docs/BUILD.md): USB-stick variant, UEFI Shell path, `diskpart` fallback for the ESP, and the troubleshooting table.

Prerequisites: UEFI boot, an ESP, Secure Boot **off**, CSM **off**, Python 3.14+, Zig 0.14.1 (one zip, no installer), ~450 MB for the pinned NVIDIA inputs.

---

## 12. Measuring

The unlock only affects `HMMA`/`IMMA` issue rate, so no GUI tool can see it — GPU-Z, HWiNFO, FurMark and AIDA64 all exercise other pipes and will report identical numbers. You need CUDA.

```powershell
powershell -File tools\build_bench.ps1                      # sm_89 probe, needs nvcc + MSVC env
powershell -File tools\bench_run.ps1 -Label unlocked
# power off -> F8 -> Windows Boot Manager (bypass the unlock) -> stock state
powershell -File tools\bench_run.ps1 -Label stock
powershell -File tools\bench_run.ps1 -Compare
```

`f16/f32` and `bf16/f32` are the controlled modes; `dp4a`, `ffma` and `s8/s32` are controls that must stay flat. Acceptance thresholds and the cuBLAS variant: [docs/BENCH.md](docs/BENCH.md).


---

## 13. Limits and open questions

- **AD104-350's response to a full-rate selector write is unresolved.** Two hypotheses are stated with the measurement that would distinguish them (§2.3, §2.4); neither has been run.
- Only one card, one board, one driver (616.56), one vBIOS has been exercised.
- The transaction requires a full AC power cycle; warm reboots are refused by design.
- `SS0`/`SS1` are volatile — the effect, if it existed, would have to be re-established on every cold boot.
- No claim is made about long-term stability under sustained tensor load, because no gain was observed to sustain.
- The GOP does not always reconnect after the FLR; the display stays dark until WDDM takes over. Cosmetic, not fatal.

---

## 14. Acknowledgements

None of this is original research. The transaction, the payload structure and the Windows UEFI plumbing all come from projects that did the hard work first. This repository is a port that pins one more board and documents where it stops.

| Project | Author | What this repository owes it |
|---|---|---|
| [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock) | Zagitta | the original Linux kernel module: PCI claim, FWSEC, SEC2, the PLM sequence and the FLR |
| [JustAResearcher/gpu-unlock-ada](https://github.com/JustAResearcher/gpu-unlock-ada) | JustAResearcher | AD102 four-PLM payload integration, DKMS/initramfs packaging, the 4090 register report and the AD103/AD106 canary reports |
| [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker) | TOTORONG | the only complete Windows UEFI port: controller ownership handoff, GOP release/restore, ESP file IO, asset pinning — the code this repository re-packages |
| [WildFlash1st/cmp90hx-unlock](https://github.com/WildFlash1st/cmp90hx-unlock) | WildFlash1st | the GA102 V67 chain and the stock-flow rejoin patches |
| [NVIDIA/open-gpu-kernel-modules](https://github.com/NVIDIA/open-gpu-kernel-modules) | NVIDIA | the published loader and booter sources the firmware assets are derived from |
| [envytools](https://github.com/envytools/envytools) | envytools contributors | Falcon / PMC register documentation that made the register map readable at all |
| [tianocore/edk2](https://github.com/tianocore/edk2) | TianoCore | the MdePkg headers used to build a freestanding UEFI application |
| Latence.app | Latence.app | the AD104 Windows port (RTX 4070 Ti, `10de:2782`) — the closest precedent to this work, and the reason AD104 looked tractable |

Earlier CMP unlocking work — [Consensus-Protocol/cmp170hx](https://github.com/Consensus-Protocol/cmp170hx), [amoghmunikote/cmpunlocker](https://github.com/amoghmunikote/cmpunlocker), and the Nouveau project — underpins the loader and the investigation that everything above builds on.

If you are one of these authors and something here misrepresents your work, please open an issue. Corrections are welcome and will be applied promptly.

### What this repository actually adds

One measurement and one packaging effort, nothing more:

- **`10de:2783` (AD104-350) executes the transaction and gains nothing** — measured, not inferred
- two hard-coded chip identities in the vendored transaction code that reject every non-GA102 card were found and fixed
- a GOP-failure halt that discarded a *successful* unlock (by demanding the power cycle that erases the volatile selectors) was found and fixed
- a read-only profiler with pin-independent preflight gates, so a new board needs two boots instead of many

Everything else — the mechanism, the payload, the UEFI structure, the AD102/AD103 results — belongs to the projects above.

### A note on how this was produced

This work was carried out almost entirely with AI assistance. The author has no
formal background in firmware, UEFI, GPU architecture or reverse engineering —
the investigation was driven by conversation, and every conclusion was checked
against logs rather than assumed.

Two consequences are worth stating plainly:

- Read the code, the analysis and these documents with that provenance in mind.
  Where a claim is unverified this repository says so; where a claim came from an
  upstream project it is attributed rather than restated as fact. The measured
  result in §1 — the transaction completes, the throughput does not change, the
  reason is still open — is the only finding here that was produced directly.
- Corrections are genuinely welcome. If you find a wrong register, a
  mis-attributed line, or a conclusion that does not follow from its evidence,
  please open an issue. Pointers are far more useful than praise, and they will
  be applied promptly.

If you have hands-on experience with GSP firmware, UEFI firmware drivers or the
Ada speed-select encoding, §2.8 and §3.5 describe exactly what is missing and
what measurement would settle it.

---

## 15. Licence

GNU GPL-2.0-only for the transaction and packaging work, inherited from the upstream projects. EDK2 headers are BSD-2-Clause-Patent. NVIDIA firmware and drivers remain under NVIDIA's terms and are **never** redistributed — `tools/fetch_assets.py` downloads the pinned inputs and derives the assets on the user's machine.

See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md), [LICENSES/](LICENSES/), and [docs/FINAL-RESULT.md](docs/FINAL-RESULT.md) for the raw logs behind every number quoted above.
