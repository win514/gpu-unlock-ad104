#!/usr/bin/env python3
"""Turn a PROFILE.TXT collected by the diag build into a pinned board header.

  python tools/profile_to_header.py usb/GU-PROFILE/RUN00/PROFILE.TXT \
      --out port/src/unlock/board_profile.generated.h

The generated header pins every value the transaction gates on, so the unlock
build refuses a different card, a different VBIOS or a changed PROM view
instead of trusting whatever it finds.
"""
import argparse
import re
from pathlib import Path

PATTERNS = {
    "chip": (r"reg_chip=0x([0-9a-f]+)", "GU_BOARD_CHIP", 0xFFFFFFFF),
    # BAR0 base is assigned by the firmware on every boot, so it is recorded
    # in the report but deliberately not pinned as a gate.
    "bar_size": (r"bar0_size=0x([0-9a-f]+)", "GU_BAR0_SIZE", 0xFFFFFFFFFFFFFFFF),
    "plm": (r"reg_feat_plm=0x([0-9a-f]+)", "GU_PLM_FEAT", 0xFFFFFFFF),
    "ss0": (r"reg_ss0=0x([0-9a-f]+)", "GU_SS0_COLD", 0xFFFFFFFF),
    "ss1": (r"reg_ss1=0x([0-9a-f]+)", "GU_SS1_COLD", 0xFFFFFFFF),
    "vram": (r"reg_vram=0x([0-9a-f]+)", "GU_VRAM_MIB", 0xFFFFFFFF),
    "rom_size": (r"rom_size=0x([0-9a-f]+)", "GU_ROM_SIZE", 0xFFFFFFFF),
    "prom_bytes": (r"prom_0_bytes=(\d+)", "GU_PROM_VIEW_BYTES", 0xFFFFFFFF),
    "prom_off": (r"prom_0_offset=0x([0-9a-f]+)", "GU_PROM_BAR_OFFSET", 0xFFFFFFFF),
}


def parse(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([a-z0-9_]+)=(.*)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profile", type=Path)
    ap.add_argument("--out", type=Path, default=Path("port/src/unlock/board_profile.generated.h"))
    a = ap.parse_args()

    p = parse(a.profile.read_text())
    lines = [
        "/* SPDX-License-Identifier: GPL-2.0-only */",
        f"/* Generated from {a.profile.name}; do not edit by hand. */",
        "#ifndef GU_BOARD_PROFILE_GENERATED_H",
        "#define GU_BOARD_PROFILE_GENERATED_H",
        "",
        f"/* source diag rows: {len(p)} */",
    ]

    dev = p.get("device_id", "")
    if ":" in dev:
        vid, did = dev.split(":")
        lines.append(f"#undef GU_BOARD_ID")
        lines.append(f"#define GU_BOARD_ID 0x{int(did, 16):04x}{int(vid, 16):04x}U")
    sub = p.get("subsystem_id", "")
    if ":" in sub:
        svid, sdid = sub.split(":")
        lines.append(f"#undef GU_BOARD_SUBSYSTEM")
        lines.append(f"#define GU_BOARD_SUBSYSTEM 0x{int(sdid, 16):04x}{int(svid, 16):04x}U")
    if "revision" in p:
        lines.append("#undef GU_BOARD_REVISION")
        lines.append(f"#define GU_BOARD_REVISION 0x{int(p['revision'], 0) & 0xFF:x}U")

    raw_text = a.profile.read_text()
    for key, (regex, macro, mask) in PATTERNS.items():
        m = re.search(regex, raw_text)
        if not m:
            continue
        value = m.group(1)
        value = int(value, 16) if regex.endswith(")") and "0x(" in regex else int(value)
        lines.append(f"#undef {macro}")
        if value > 0xFFFFFFFF or macro in ("GU_BAR0_ADDR", "GU_BAR0_SIZE"):
            lines.append(f"#define {macro} 0x{value:x}ULL")
        else:
            lines.append(f"#define {macro} 0x{value & mask:x}U")

    for key, macro in (("rom_sha256", "GU_ROM_SHA256"), ("prom_0_sha256", "GU_PROM_VIEW_SHA256")):
        if key in p and re.fullmatch(r"[0-9a-f]{64}", p[key]):
            lines.append(f"#undef {macro}")
            lines.append(f'#define {macro} "{p[key]}"')

    lines += ["", "#endif", ""]
    a.out.write_text("\n".join(lines))

    pinned = [l for l in lines if l.startswith("#define")]
    print(f"wrote {a.out} with {len(pinned)} pinned values")
    for l in pinned:
        print("  " + l)
    print("\nCoverage check (a value that stays 0 disables that gate):")
    for key, (regex, _macro, _mask) in PATTERNS.items():
        m = re.search(regex, raw_text)
        print(f"  {key:12s} {'pinned' if m else 'NOT FOUND -> gate disabled'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
