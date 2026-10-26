#!/usr/bin/env python3
"""Windows-side preflight for the re-packaged GPU unlock port.

Runs on the live machine, reads only PnP/CIM data, writes nothing to the GPU and
produces the identity part of the profile the UEFI build needs.
"""
import json
import re
import subprocess
import sys

PS = ["powershell", "-NoProfile", "-Command"]
PS_GPU = ("Get-CimInstance Win32_VideoController | "
          "Select-Object Name,DriverVersion,PNPDeviceID,Status | ConvertTo-Json -Compress")
PS_SECURE = ("try { (Confirm-SecureBootUEFI) } catch { 'unknown' }")
PS_FW = ("(Get-CimInstance Win32_ComputerSystem).Manufacturer + ' | ' + "
         "(Get-CimInstance Win32_ComputerSystem).Model + ' | ' + "
         "(Get-CimInstance Win32_BIOS).SMBIOSBIOSVersion")
PS_SIG = "(Get-AuthenticodeSignature '{path}').Status"

# 616.56 / 32.0.16.1656 as installed on this machine. A different driver build
# only changes this baseline value, not the audit conclusion.
KNOWN_DRIVER_SHA = "39f23e999f4ec35f592196e61d1a49438e91066762834d412a8eb86f0f14dbd2"


def find_driver():
    import glob
    from pathlib import Path
    pattern = "C:\\Windows\\System32\\DriverStore\\FileRepository\\nv*\\nvlddmkm.sys"
    hits = sorted(glob.glob(pattern))
    return Path(hits[-1]) if hits else None


def ps(cmd: str) -> str:
    r = subprocess.run(PS + [cmd], capture_output=True, text=True)
    return (r.stdout or r.stderr).strip()


def main() -> int:
    gpus = json.loads(ps(PS_GPU) or "[]")
    if isinstance(gpus, dict):
        gpus = [gpus]

    print("=" * 72)
    print("GPU PREFLIGHT - re-packaged AD102-family port")
    print("=" * 72)

    target = None
    for g in gpus:
        pnp = g.get("PNPDeviceID") or ""
        m = re.match(r"PCI\\VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})&SUBSYS_([0-9A-F]{8})&REV_([0-9A-F]{2})", pnp)
        print(f"\n  {g.get('Name')}")
        print(f"    driver      : {g.get('DriverVersion')}")
        print(f"    pnp         : {pnp or '-'}")
        if m:
            vid, did, subsys, rev = m.groups()
            print(f"    ids         : {vid.lower()}:{did.lower()}  subsys={subsys.lower()}  rev={rev.lower()}")
            if did.upper() == "2783":
                target = (vid.lower(), did.lower(), subsys.lower(), rev.lower())

    print("\n" + "-" * 72)
    secure = ps(PS_SECURE)
    fw = ps(PS_FW)
    print(f"Secure Boot : {secure}")
    print(f"Platform    : {fw}")

    # --- driver integrity: the unlock path assumes a stock, unpatched driver
    print("\n" + "-" * 72)
    import hashlib
    driver = find_driver()
    if driver:
        blob = driver.read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        print(f"driver      : {driver}")
        print(f"  bytes     : {len(blob)}")
        print(f"  sha256    : {digest}")
        verdict = ("stock (matches the audited 616.56 build)"
                   if digest == KNOWN_DRIVER_SHA
                   else "UNEXPECTED HASH - patched or a different build")
        print(f"  verdict   : {verdict}")
        print(f"  signature : {ps(PS_SIG.format(path=str(driver)))}")
    else:
        print("driver      : nvlddmkm.sys not found under DriverStore")

    if not target:
        print("\nRESULT: no 10de:2783 (RTX 4070 SUPER / AD104) found.")
        print("        This package is pinned to that device; nothing else is admitted.")
        return 1

    vid, did, subsys, rev = target
    svid, sdid = subsys[4:8], subsys[0:4]
    print("\nRESULT: target device present - profile identity block for build.py:")
    print(f"  -DGU_BOARD_ID=0x{did}{vid}U")
    print(f"  -DGU_BOARD_SUBSYSTEM=0x{sdid}{svid}U")
    print(f"  -DGU_BOARD_REVISION=0x{rev}U")
    print("\nStill required from the UEFI diag run (Windows cannot read them):")
    print("  chip id, BAR0 base, cold PLM/SS0/SS1/VRAM, ROM size+sha256, PROM view hash")
    if secure.lower() != "false":
        print("\nNOTE: Secure Boot is on/unknown. The unsigned EFI will not load;")
        print("      turn it off for the diag/USB boot or the firmware will refuse it.")
    return 0 if secure.lower() == "false" else 2


if __name__ == "__main__":
    sys.exit(main())
