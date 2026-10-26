# Architecture

## The problem

Consumer GeForce Ada parts ship with the tensor issue rate halved in the vBIOS
feature configuration. `FEAT` permission is closed, and the two speed-select
registers hold "half rate" field encodings:

| Register | BAR0 offset | Cold value (RTX 4070 SUPER) |
|---|---|---|
| WPR_CFG PLM | `0x1fa7cc` | `0x0004cb8f` |
| WPR PLM | `0x1fa7c4` | `0x0004cb8f` |
| FBPA PLM | `0x9a0148` | `0xffffff0f` |
| FEAT PLM | `0x823804` | `0xffffff8f` |
| SS0 | `0x82381c` | `0x53467150` |
| SS1 | `0x823820` | `0x7` |
| effective readout | `0x823818` | `0x00410080` |

Direct host writes to the feature permission register and to the selectors are
ignored: the write needs the privilege of authenticated firmware.

## The chain

```
host: claim cold card, save PCI state, allocate DMA
  ↓
board ROM: signed FWSEC-FRTS on the GSP Falcon        (firmware reservation, WPR2)
  ↓
SEC2: unchanged signed AD102 booter + crafted V67 signature data
      → WPR_CFG → FBPA → WPR → FEAT protected writes
      → mailbox 0x67b00001, HALT
  ↓
host: require marker + HALT + permission readbacks + PCI/BAR access
  ↓
host: SS0 = 0x88888888, SS1 = 0x8, verify nine speed-select fields read 0
  ↓
host: one PCIe FLR, verify FEAT/selector state survived
  ↓
stock NVIDIA driver initializes from a clean, halted GSP
```

Nothing is decrypted on the host and no host code enters the authenticated
image. The crafted signature block overwrites stack slots so that the booter's
own authenticated instructions perform the writes.

## Payload

`v67-ad102-610.43.03-four-plm.bin` is **data**, not code:

- 64 000 bytes (`0xfa00`) of repeated canary dword `0x0000019c`
- 27 patched dwords at `0x1100` and `0xf948…0xf9fc`

| Offset | Value | Role |
|---|---|---|
| `0x1100` | `0x00000007` | inherited `D[0x1700]=7` semantics |
| `0xf948` | `0xfffff0ff` | WPR_CFG target value |
| `0xf950` | `0x000021b2` | argument setup gadget (`mov b32 $r10 $r0`) |
| `0xf960` | `0x001fa7cc` | WPR_CFG address |
| `0xf968` | `0x000033fc` | return tail (`mov b32 $r11 $r10`) |
| `0xf97c` | `0x0000256f` | BAR-write helper |
| `0xf984` / `0xf9a8` / `0xf9cc` | `0x9a0148` / `0x1fa7c4` / `0x823804` | FBPA / WPR / FEAT addresses |
| `0xf9e0` | `0x67b00001` | mailbox marker |
| `0xf9ec` / `0xf9f8` / `0xf9fc` | `0x7a02` / `0x31b5` / `0x771e` | cleanup tail: SP load, status writer, exit |

`tools/gen_payload.py` re-derives all of this from the documented structure and
asserts byte equality with the released payload.

Important: `0xf94c`/`0xf950` are **file offsets**; they map to DMEM
`0xff4c`/`0xff50` using copy base `0x600`. Treating file offsets as DMEM
addresses misdescribes the stack layout.

## UEFI application structure

```
src/unlock/
├─ app.c            main flow, gates, arming, handoff orchestration
├─ app_io.c         ESP volume, run directory, REPORT.TXT, asset loading
├─ ownership.c      exclusive controller claim and firmware driver release
├─ handoff.inc      Windows preload, GOP reconnect, StartImage
├─ checks.c         PCI config-space and device-path validation
├─ port.c           BAR0 mapping, MMIO guards, DMA lifetime
├─ diag.c           read-only profile collector (GU_DIAG_MODE)
├─ board_profile.h  every hardware fingerprint, all overridable
└─ vendor/          the retained kernel transaction (FWSEC, SEC2, PLM, FLR)
```

`GuWrite32` requires `armed && owned && display_ok`; the profiling mode never
sets any of them, so the write path is unreachable there by construction.

## Gates

The transaction only runs when all of these hold. Every value comes from
`board_profile.h`:

1. exactly one device matches `GU_BOARD_ID` and `GU_BOARD_SUBSYSTEM`
2. `BAR0` is memory-mapped, `GU_BAR0_SIZE` bytes, with matching command bits
3. `chip` (BAR0+0) equals `GU_BOARD_CHIP`
4. `FEAT PLM` / `SS1` / `VRAM` equal the recorded cold values
5. `(SS0 & 0x88888888) == 0` — nothing is already at full rate
6. option ROM size/digest and PROM view digest match the pinned board
7. the five firmware assets verify against pinned SHA-256
8. Windows Boot Manager is preloaded and reachable

Failure at any gate stops before any write. Failure during the transaction
retains DMA buffers and halts deliberately, because a partially torn-down GSP
cannot be trusted — power off is the only safe exit.

## Why the timing has to be pre-driver

`WPR_CFG`, `WPR` and `FEAT` are protected by the firmware's WPR2 reservation.
Once the GSP starts, that window belongs to the firmware and the selectors are
re-established from its own state. The transaction therefore has to complete
before the NVIDIA driver binds — which is why this is a UEFI application and not
a driver, a service, or a userspace tool.
