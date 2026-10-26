# Third-party notices

This repository combines work from several GPL-2.0 projects plus BSD-licensed
EDK2 headers. Nothing from NVIDIA is redistributed: firmware and drivers are
downloaded and derived locally at build time.

## Vendored source

| Component | Origin | Licence |
|---|---|---|
| `src/unlock/` kernel transaction, prep, VBIOS and gfw-eval code | [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock) via [JustAResearcher/gpu-unlock-ada](https://github.com/JustAResearcher/gpu-unlock-ada) | GPL-2.0-only |
| `src/unlock/app.c`, `app_io.c`, `ownership.c`, `handoff.inc`, `format.c`, `runtime.c`, `sha256.c`, `port.*`, `checks.*` (UEFI layer) | [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker) | GPL-2.0 |
| `src/firmware-tools/` | same donor project | GPL-2.0 |
| GA102 V67 chain (referenced, not vendored) | [WildFlash1st/cmp90hx-unlock](https://github.com/WildFlash1st/cmp90hx-unlock) | GPL-2.0-only |
| `src/deps/edk2/MdePkg/Include/` | [tianocore/edk2](https://github.com/tianocore/edk2) | BSD-2-Clause-Patent |

The AD102 four-PLM payload structure derives from published decrypted
debug-booter analysis in the donor project. `tools/gen_payload.py` re-derives it
from that documented structure and asserts byte equality with the released
payload.

## Not redistributed (fetched at build time)

| Asset | Rights holder | Handling |
|---|---|---|
| `NVIDIA-kernel-module-source-610.43.03.tar.xz` | NVIDIA Corporation | downloaded from download.nvidia.com, SHA-256 pinned |
| `nvidia-utils-610.43.03-1-x86_64_v3.pkg.tar.zst` | NVIDIA / CachyOS packaging | downloaded from the CachyOS archive, SHA-256 pinned |
| `gsp_ga10x.bin` and the derived booter assets | NVIDIA Corporation | generated locally from the two archives above; the resulting files stay under NVIDIA's terms |
| `nvlddmkm.sys` (driver) | NVIDIA Corporation | never included; the driver is not modified by this project |

NVIDIA's own notices are preserved in `LICENSES/NVIDIA-MIT.txt`. The booter and
GSP images remain subject to NVIDIA's licence; this repository only automates
deriving them on the user's own machine.

## Patches applied to the vendored code

See `patch.py` for the exact, assertion-checked list. Summary:

1. Board identity, BAR size, cold-state expectations, ROM/PROM hashes moved to
   `board_profile.h`.
2. Two hard-coded chip identities in `vendor/unlock_610.c` (`0x220410de` GA102,
   `0x193000a1` AD103) replaced with profile values.
3. UEFI medium check relaxed, run-root auto-created, class-mask literal fixed.
4. Display handoff no longer halts when the firmware GOP does not reconnect.
5. Unattended arming mode (`GU_AUTO_ARM`) and a longer manual arming window.
