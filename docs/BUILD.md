# Build and deploy

Everything runs on Windows. No Linux, WSL, Visual Studio or MinGW is required —
the UEFI image is cross-compiled with `zig cc -target x86_64-uefi`.

## 0. Prerequisites

| Item | Why |
|---|---|
| Windows 10/11 with **UEFI** boot (not legacy/CSM) | the image is an `EFI_APPLICATION` |
| An EFI System Partition (ESP) | the run directory and the image live there |
| **Secure Boot disabled** | the image is unsigned |
| Python 3.14+ | `compression.zstd` is used to read the `.pkg.tar.zst` archive |
| Zig 0.14.1 | `zig-x86_64-windows-0.14.1.zip`, unpack anywhere |
| ~450 MB free disk | 26 MB + 314 MB pinned NVIDIA inputs, plus 84 MB of derived assets |

## 1. Generate the firmware assets

```powershell
python tools\fetch_assets.py
```

Downloads the two pinned archives into `downloads\`, verifies their SHA-256,
then derives:

```
build\assets\booter_load_ad102.bin          57 672 B
build\assets\gsp_boot_ad102.bin             36 864 B
build\assets\gsp_boot_desc_ad102.bin            84 B
build\assets\gsp_ga10x.bin              84 277 400 B
build\assets\v67-ad102-610.43.03-four-plm.bin  64 000 B
```

All five are checked against pinned digests at the end of the run. Use
`--cache <dir>` to reuse an existing download, or `--verify-only` to re-check
without network access.

## 2. Build the read-only profiler

```powershell
python build.py --zig C:\path\to\zig.exe --mode diag
```

Output: `port`-independent path `build\diag\EFI\BOOT\BOOTX64.EFI` (≈72 KB).

## 3. Deploy to the internal ESP

Administrator PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File tools\esp_deploy.ps1 -Mode diag -RegisterBootEntry
```

The script mounts the ESP through `Add-PartitionAccessPath`, copies
`\EFI\GU\GU.EFI`, creates `\GU-PROFILE`, optionally registers a `GU-DIAG`
firmware boot entry, then unmounts. It never touches `\EFI\Microsoft`,
`bootmgfw.efi` or the default boot order.

Without the script (fallback):

```
diskpart
select disk 0
select partition 1
assign letter=Z
exit
```

```powershell
New-Item -ItemType Directory -Force Z:\EFI\GU, Z:\GU-PROFILE
Copy-Item build\diag\EFI\BOOT\BOOTX64.EFI Z:\EFI\GU\GU.EFI
```

## 4. Collect the profile

Reboot, open the boot menu (F8), pick `GU-DIAG` (or `Boot From File → EFI → GU → GU.EFI`).

The profiler is **read-only**: it enumerates PCI, requires a single matching
device, reads the 256-byte config space, BAR0, 21 named registers, the option
ROM and the PROM view, writes `\GU-PROFILE\RUN00\PROFILE.TXT`, then cold-reboots
by itself. It never writes MMIO.

## 5. Pin the profile and build the unlock image

```powershell
powershell -ExecutionPolicy Bypass -File tools\esp_recover.ps1     # pulls PROFILE.TXT to out\GU-PROFILE
python tools\profile_to_header.py out\GU-PROFILE\RUN00-PROFILE.TXT
python build.py --zig C:\path\to\zig.exe --mode unlock --auto
```

`profile_to_header.py` writes `src/unlock/board_profile.generated.h`, which
`board_profile.h` picks up automatically. The gates pinned from it:

| Macro | Source field |
|---|---|
| `GU_BOARD_ID` / `GU_BOARD_SUBSYSTEM` / `GU_BOARD_REVISION` | `device_id`, `subsystem_id`, `revision` |
| `GU_BOARD_CHIP` | `reg_chip` |
| `GU_BAR0_SIZE` | `bar0_size` (address is *not* pinned: firmware reassigns it) |
| `GU_PLM_FEAT` | `reg_feat_plm` |
| `GU_SS0_COLD` / `GU_SS1_COLD` | `reg_ss0`, `reg_ss1` |
| `GU_VRAM_MIB` | `reg_vram` |
| `GU_ROM_SIZE` / `GU_ROM_SHA256` | `rom_size`, `rom_sha256` |
| `GU_PROM_VIEW_BYTES` / `_SHA256` / `_BAR_OFFSET` | `prom_0_*` |

`SS0` is recorded, not gated: the gate is "no field is already 8", i.e.
`(SS0 & 0x88888888) == 0`.

## 6. Deploy the unlock image

```powershell
powershell -ExecutionPolicy Bypass -File tools\esp_deploy.ps1 -Mode unlock -Auto -RegisterBootEntry
```

Add `-SetDefault` to make `GU-DIAG` the first firmware boot entry, so every
power-on unlocks automatically without a key press.

## 7. Cold boot

**Full power-off is mandatory for the first attempt**: shut down, unplug the
power cord, wait 30 seconds, plug back in, power on.

The GSP's WPR2 window and SEC2 state do not reset across a warm reboot, so a
restart will be refused at the `cold-state` gate (`status=0x6`, five-second
pause, then Windows boots normally without unlocking).

Successful run, in the report:

```
cold state: ... SS0=0x53467150 SS1=0x7
AD102 SINGLE RESULT: marker=0x67b00001 marker_ok=1 cpuctl=0x10
SELECTOR RESULT: SS0 before=... after=0x88888888 matched=1
SELECTOR RESULT: SS1 before=0x7 after=0x8 matched=1
POST-FLR  SS0=0x88888888 SS1=0x00000008
POST-GOP  SS0=0x88888888 SS1=0x00000008
FINAL status=0 stage=post-unlock-handoff attempted=1 driver_release=1 clean=1
```

## 8. Verify the state from Windows (optional)

`SS0`/`SS1` are volatile. To confirm they are still set while Windows is
running, read BAR0 from a tool that can map MMIO (RWEverything or similar):

- `BAR0 + 0x82381C` should read `0x88888888`
- `BAR0 + 0x823820` should read `0x00000008`

A value of `0xBADF5620` or `0xFFFFFFFF` means the read was rejected (no PRIV
access), not that the unlock is missing.

There is no CUDA-free way to measure tensor throughput. If you want numbers,
compile `mma_bench`-style kernels with the CUDA Toolkit and compare stock vs
unlocked on the same clocks and power limit.

## 9. Rollback

```powershell
bcdedit /set {fwbootmgr} displayorder {current} /addfirst   # Windows first again
bcdedit /delete {your-GU-DIAG-guid}                          # remove the entry
powershell -ExecutionPolicy Bypass -File tools\esp_recover.ps1 -Cleanup
```

The last command deletes `\EFI\GU` and `\GU-PROFILE` from the ESP. No driver,
service, bootloader file or firmware setting is modified at any point.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Preflight or logging failed` | ESP volume could not be opened | check the deploy step; the run root is created automatically |
| `CHECK stage=target status=0x8000000000000002` | wrong device/subsystem | re-run the profiler, regenerate the header |
| `CHECK stage=cold-state status=0x8000000000000006` | WPR2 still reserved, or SS0/SS1 read as 0 | full AC power cycle, wait 30 s |
| `CHECK stage=prom status=0x8000000000000008` | ROM/PROM hash mismatch (different BIOS) | re-profile; do not "fix" the pin by clearing it |
| `display reconnect degraded` | firmware GOP not rebound after FLR | harmless; Windows re-initializes the GPU |
| `STOP: cleanup cannot be proven` | transaction failed mid-flight | hold power 10 s, unplug 30 s; report the `RUNnn` log |
