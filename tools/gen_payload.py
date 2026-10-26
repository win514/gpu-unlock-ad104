#!/usr/bin/env python3
"""Independent reconstruction of the AD102 610.43.03 four-PLM payload.

The payload is not firmware: it is data the signed booter consumes. Structure
recovered from the released generator plus the register report:

  * image is 0xfa00 bytes of repeated canary dword 0x0000019c;
  * one header field at 0x1100 = 7 (inherited D[0x1700]=7 semantics);
  * a first block at 0xf948..0xf97c sets the WPR_CFG target + value and the
    three helper entry addresses (0x21b2 argument setup, 0x33fc return tail,
    0x256f BAR-write helper);
  * three more blocks at 0xf980 / 0xf9a4 / 0xf9c8 repeat that shape for FBPA,
    WPR and FEAT, with the mailbox marker 0x67b00001 carried in the last slot;
  * a cleanup tail at 0xf9ec: 0x7a02 (load SP into r9), 0x31b5 (status writer),
    0x771e (exit) -- the cleanup path the kernel module calls when the marker
    is present.

Asserts:
  1. the reconstruction is byte-identical to the released payload,
  2. the four PLM targets stay in the published order.

Run: python analysis/gen_payload.py
"""
import argparse
import hashlib
import struct
from pathlib import Path

SIZE = 0xFA00
FILL = 0x0000019C
MARKER = 0x67B00001

# Ordered PLM writes: address -> value.  FBPA is observational (it did not
# change on hardware) but the chain still issues the store.
TARGETS = [
    (0x1FA7CC, 0xFFFFF0FF),   # WPR_CFG
    (0x9A0148, 0xFFFFFFFF),   # FBPA
    (0x1FA7C4, 0xFFFFFFFF),   # WPR
    (0x823804, 0xFFFFFFFF),   # FEAT
]

SHIPPED_SHA = "44c36b2d6b3424e53e18f3e55db85c833655de071ce66ce42749588a4a7dc8cb"
SHIPPED = Path(__file__).resolve().parents[1] / "build" / "assets" / "v67-ad102-610.43.03-four-plm.bin"

# Gadget entry points inside the AD102 booter (Falcon IMEM addresses).
ARG_SETUP = 0x7A02      # mov $r9 $sp
ARG_VALUE = 0x21B2      # mov b32 $r10 $r0
RETURN_TAIL = 0x33FC    # mov b32 $r11 $r10
BAR_WRITE = 0x256F      # add $sp -0x4 ... BAR write helper
STATUS_WRITER = 0x31B5
EXIT = 0x771E


def patch_map(targets=TARGETS) -> dict:
    pm = {0x1100: 7, 0xF948: targets[0][1], 0xF950: ARG_VALUE,
          0xF960: targets[0][0], 0xF968: RETURN_TAIL, 0xF974: 0xFFFFFFFF,
          0xF97C: BAR_WRITE}
    for i, base in enumerate((0xF980, 0xF9A4, 0xF9C8), start=1):
        pm.update({
            base: ARG_SETUP,
            base + 4: targets[i][0],
            base + 12: RETURN_TAIL,
            base + 24: 0xFFFFFFFF if i < 3 else MARKER,
            base + 32: BAR_WRITE,
        })
    pm.update({0xF9EC: ARG_SETUP, 0xF9F8: STATUS_WRITER, 0xF9FC: EXIT})
    return pm


def build(pm=None) -> bytes:
    pm = patch_map() if pm is None else pm
    img = bytearray(struct.pack("<I", FILL) * (SIZE // 4))
    for off, val in pm.items():
        if off % 4 or off + 4 > SIZE:
            raise ValueError(f"bad patch offset {off:#x}")
        struct.pack_into("<I", img, off, val)
    return bytes(img)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="write the payload here instead of only verifying")
    a = ap.parse_args()
    img = build()
    digest = hashlib.sha256(img).hexdigest()
    print(f"reconstructed {len(img)} bytes sha256={digest}")
    assert digest == SHIPPED_SHA, "reconstruction does not match the released payload"
    if SHIPPED.exists():
        assert SHIPPED.read_bytes() == img, "byte comparison failed"
        print(f"byte-identical to {SHIPPED.relative_to(SHIPPED.parents[2])}")

    print("\npatch map (file offset -> dword):")
    for off, val in sorted(patch_map().items()):
        tag = ""
        for i, (addr, _) in enumerate(TARGETS):
            if val == addr:
                tag = f"target #{i} address"
        if val == MARKER:
            tag = "mailbox marker"
        print(f"  {off:#06x}  {val:#010x}  {tag}")
    print("\nwrite order:", " -> ".join(f"{t:#x}={v:#x}" for t, v in TARGETS))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_bytes(img)
        print(f"wrote {a.out} ({len(img)} bytes)")
    print("\nNote: the canary at 0xf94c/0xf950 maps to DMEM 0xff4c/0xff50 with")
    print("copy base 0x600, so file offsets are not DMEM addresses.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
