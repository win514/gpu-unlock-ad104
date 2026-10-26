#!/usr/bin/env python3
"""Assemble a bootable FAT32 payload tree for the re-packaged port.

Layout the UEFI application expects:

  <usb>/EFI/BOOT/BOOTX64.EFI
  <usb>/GU-PROFILE/ASSETS/<five pinned assets>
  <usb>/GU-PROFILE/RUNnn/{REPORT.TXT,PROFILE.TXT,PROM.BIN}   (created by the EFI)
"""
import argparse
import hashlib
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ASSETS = ["booter_load_ad102.bin", "v67-ad102-610.43.03-four-plm.bin",
          "gsp_ga10x.bin", "gsp_boot_ad102.bin", "gsp_boot_desc_ad102.bin"]
PINNED = {
    "booter_load_ad102.bin": "6ee05b20e1dc244c08c052f36ef28469b8d09f4955d1fe33e48a179e11a7fd49",
    "v67-ad102-610.43.03-four-plm.bin": "44c36b2d6b3424e53e18f3e55db85c833655de071ce66ce42749588a4a7dc8cb",
    "gsp_ga10x.bin": "572373620a37418f24dc16b5031c39338778c3257e48e8408de9a57291b24f3a",
    "gsp_boot_ad102.bin": "45d6335a8185d6ff13e8d1484cea73f68d3d13aa1c19dc080ed1c3482dd5bac0",
    "gsp_boot_desc_ad102.bin": "83f8f3f1f5f9496e0ea8fc7103c2beb64d0b6de2f5ffe725f13514de5a95fa42",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE / "usb")
    ap.add_argument("--efi", type=Path)
    ap.add_argument("--mode", choices=["diag", "unlock"], default="diag")
    a = ap.parse_args()

    efi = a.efi or (HERE / "port" / "build" / a.mode / "EFI" / "BOOT" / "BOOTX64.EFI")
    if not efi.exists():
        return f"missing EFI: {efi}"  # type: ignore[return-value]

    boot = a.out / "EFI" / "BOOT"
    runroot = a.out / "GU-PROFILE"
    assets = runroot / "ASSETS"
    boot.mkdir(parents=True, exist_ok=True)
    runroot.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)

    shutil.copy2(efi, boot / "BOOTX64.EFI")
    print(f"EFI: {boot / 'BOOTX64.EFI'} <- {efi}")

    src = HERE / "build" / "assets"
    missing = []
    for name in ASSETS:
        p = src / name
        if not p.exists():
            missing.append(name)
            continue
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        flag = "OK" if digest == PINNED[name] else "MISMATCH"
        shutil.copy2(p, assets / name)
        print(f"asset: {name} {p.stat().st_size} bytes {flag}")
    if missing:
        print("missing assets:", ", ".join(missing))
    print(f"\nUSB tree ready at {a.out} ({a.mode} mode)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
