# Contributing

The most useful contribution is **a verified result on a different card**. The
pipeline is deliberately built so that adding a board is data, not code.

## Before you open an issue

Run the read-only profiler and attach `PROFILE.TXT`. It contains the device id,
subsystem, chip id, BAR geometry, cold register values and the ROM/PROM hashes —
everything needed to tell whether a board is a plausible candidate.

The profiler never writes MMIO, so it is safe on any supported card.

## Adding a board

1. **Profile.** Build with `--mode diag`, deploy to the ESP, cold boot it, collect
   `GU-PROFILE\RUNnn\PROFILE.TXT`.
2. **Pin.** `python tools\profile_to_header.py <PROFILE.TXT>` writes
   `src/unlock/board_profile.generated.h`. Do not commit that file — it is
   machine-specific and already in `.gitignore`.
3. **Extend admission.** Add the device id to `supported_ids[]` in
   `src/unlock/main.c` *and* to the AD103/AD106-style gates in
   `src/unlock/port.c` if the part is not a plain AD102 family member. Keep the
   "experimental" style gate: a new id must require an explicit PCI address,
   never `targets=all`.
4. **Build and run.** `--mode unlock --auto`, cold boot, keep the report.
5. **Measure.** `tools\build_bench.ps1` then `tools\bench_run.ps1` in both
   states; see [docs/BENCH.md](docs/BENCH.md). A transaction without a
   measurement is not a result.

## What to send

A pull request or issue containing:

- `PROFILE.TXT` (read-only run)
- the `REPORT.TXT` of one successful transaction (`FINAL status=0`, `clean=1`)
- `stock.json` and `unlocked.json` from `bench_run.ps1`, plus `-Compare` output
- device model, subsystem id, vBIOS version, driver version, power limit
- whether it worked, and if it did not, the exact `CHECK stage=` line

## What not to send

- NVIDIA firmware, drivers, or any `.bin`/`.sys`/`.efi` derived from them
- your board profile header (it is in `.gitignore` on purpose)
- "it works" without a report — the whole point of this repository is that a
  transaction can succeed and still change nothing (see README §2)

## Code changes

- Keep the `board_profile.h` pattern: any new hardware constant goes there with a
  `0`/`""` default meaning "record, do not gate".
- Never relax a gate to make a run pass. If a gate is wrong, fix the value it
  compares against and say why in the commit message.
- Failures must stay fail-closed: if the transaction cannot prove the firmware
  stopped, the application halts and asks for a power cycle.
- Match the existing style: freestanding C11, no libc, `-Wall -Wextra -Werror`.
- Run `python build.py --zig <zig> --mode diag` and `--mode unlock` before
  submitting; both must build with no warnings.
