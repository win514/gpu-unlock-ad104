#!/usr/bin/env python3
"""Build the re-packaged UEFI application.

  python build.py --zig <path-to-zig.exe> --mode diag    -> read-only profiler
  python build.py --zig <path-to-zig.exe> --mode unlock  -> transaction build
  python build.py --zig ... --mode unlock --profile PROFILE.TXT

--profile parses a PROFILE.TXT produced by the diag build and turns every
observed value into the corresponding -D so the unlock build gates on this
exact board instead of a generic wildcard.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"

SOURCES = [
    "app", "app_io", "ownership", "format", "runtime", "sha256", "checks",
    "port", "compat", "diag",
    "vendor/unlock_610", "vendor/prep_610", "vendor/layout_610",
    "vendor/vbios_610", "vendor/gfw_eval",
]


def parse_profile(path: Path) -> dict:
    values = {}
    for line in path.read_text().splitlines():
        m = re.match(r"^([a-z0-9_]+)=(.*)$", line.strip())
        if not m:
            continue
        values[m.group(1)] = m.group(2)
    return values


def profile_defines(p: dict) -> list:
    out = []

    def num(key, macro, mask=0xFFFFFFFF):
        raw = p.get(key)
        if raw is None:
            return
        raw = raw.strip()
        try:
            v = int(raw, 0)
        except ValueError:
            return
        out.append(f"-D{macro}=0x{v & mask:x}U")

    num("device_id_hi", "GU_BOARD_DEVICE_HI")
    # device id line looks like "device_id=10de:2783"
    dev = p.get("device_id", "")
    if ":" in dev:
        vid, did = dev.split(":", 1)
        try:
            out.append(f"-DGU_BOARD_ID=0x{int(did,16):04x}{int(vid,16):04x}U")
        except ValueError:
            pass
    sub = p.get("subsystem_id", "")
    if ":" in sub:
        svid, sdid = sub.split(":", 1)
        try:
            out.append(f"-DGU_BOARD_SUBSYSTEM=0x{int(sdid,16):04x}{int(svid,16):04x}U")
        except ValueError:
            pass
    num("revision", "GU_BOARD_REVISION", 0xFF)
    num("reg_chip", "GU_BOARD_CHIP")
    num("bar0_addr", "GU_BAR0_ADDR", 0xFFFFFFFFFFFFFFFF)
    num("bar0_size", "GU_BAR0_SIZE", 0xFFFFFFFFFFFFFFFF)
    num("reg_feat_plm", "GU_PLM_FEAT")
    num("reg_ss0", "GU_SS0_COLD_SS0")
    num("reg_ss1", "GU_SS1_COLD")
    num("reg_vram", "GU_VRAM_MIB")
    num("rom_size", "GU_ROM_SIZE")
    rom = p.get("rom_sha256")
    if rom:
        out.append(f'-DGU_ROM_SHA256="{rom}"')
    prom = p.get("prom_0_bytes_sha256") or p.get("prom_sha256")
    if prom:
        out.append(f'-DGU_PROM_VIEW_SHA256="{prom}"')
    if p.get("prom_0_bytes"):
        try:
            out.append(f"-DGU_PROM_VIEW_BYTES=0x{int(p['prom_0_bytes'],0):x}U")
        except ValueError:
            pass
    off = p.get("prom_0_offset")
    if off:
        try:
            out.append(f"-DGU_PROM_BAR_OFFSET=0x{int(off,0):x}U")
        except ValueError:
            pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zig", required=True)
    ap.add_argument("--mode", choices=["diag", "unlock"], default="unlock")
    ap.add_argument("--auto", action="store_true",
                    help="unlock build that starts the transaction without a key press")
    ap.add_argument("--profile", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--extra", action="append", default=[])
    a = ap.parse_args()

    defines = [f"-DGU_DIAG_MODE={1 if a.mode == 'diag' else 0}"]
    if a.auto:
        defines.append("-DGU_AUTO_ARM=1")
    if a.profile:
        if not a.profile.exists():
            sys.exit(f"profile not found: {a.profile}")
        defines += profile_defines(parse_profile(a.profile))
    defines += a.extra

    tag = "unlock-auto" if (a.mode == "unlock" and a.auto) else a.mode
    out = a.out or (HERE / "build" / tag / "EFI" / "BOOT" / "BOOTX64.EFI")
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        a.zig, "cc", "-target", "x86_64-uefi", "-std=c11", "-ffreestanding",
        "-fno-builtin", "-fno-stack-protector", "-mno-red-zone", "-fshort-wchar",
        "-Os", "-g0", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
        # board_profile.h values are compile-time constants on purpose; the
        # profile gates are runtime data once observed on a board.
        "-Wno-constant-logical-operand",
        *(["-Wno-unused-function"] if a.mode == "diag" else []),
        "-D__KERNEL__", "-DGU_UEFI_PORT",
        *defines,
        "-I" + str(SRC / "unlock" / "compat"),
        "-I" + str(SRC / "deps" / "edk2" / "MdePkg" / "Include"),
        "-I" + str(SRC / "deps" / "edk2" / "MdePkg" / "Include" / "X64"),
        "-nostdlib",
        *[str(SRC / "unlock" / f"{s}.c") for s in SOURCES],
        "-o", str(out),
    ]
    print(" ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode:
        return r.returncode

    blob = out.read_bytes()
    report = {
        "mode": a.mode,
        "artifact": str(out),
        "size": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "defines": defines,
        "hardware_tested": False,
    }
    (HERE / "build" / f"build-result-{tag}.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
