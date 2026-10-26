#!/usr/bin/env python3
"""Fetch the pinned NVIDIA inputs and generate the firmware assets locally.

Nothing proprietary is redistributed with this repository. The build downloads
two NVIDIA/CachyOS archives over HTTPS, verifies their SHA-256 against a pinned
manifest, and derives the four boot-time assets plus the payload from them.

  python tools/fetch_assets.py                  # download into ./downloads, assets into ./build/assets
  python tools/fetch_assets.py --cache D:\\dl    # reuse an existing cache
  python tools/fetch_assets.py --verify-only    # check an existing cache, no network

Outputs (all SHA-256 checked):
  build/assets/booter_load_ad102.bin
  build/assets/gsp_boot_ad102.bin
  build/assets/gsp_boot_desc_ad102.bin
  build/assets/gsp_ga10x.bin
  build/assets/v67-ad102-610.43.03-four-plm.bin
"""
import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "src" / "firmware-tools"

SOURCES = {
    "NVIDIA-kernel-module-source-610.43.03.tar.xz": {
        "url": "https://download.nvidia.com/XFree86/NVIDIA-kernel-module-source/"
               "NVIDIA-kernel-module-source-610.43.03.tar.xz",
        "sha256": "7e118923c7a23edc36114d63273a46e3e04e9af98695a42203e7ac2dfe9fc1dc",
    },
    "nvidia-utils-610.43.03-1-x86_64_v3.pkg.tar.zst": {
        "url": "https://archive.cachyos.org/archive/cachyos-v3/"
               "nvidia-utils-610.43.03-1-x86_64_v3.pkg.tar.zst",
        "sha256": "e17e7c92eeffa178b0fe1f40eb17a47095f8fc3ce4a77bf115cf5bd5a4df86e9",
    },
}

ASSETS = {
    "booter_load_ad102.bin": "6ee05b20e1dc244c08c052f36ef28469b8d09f4955d1fe33e48a179e11a7fd49",
    "gsp_boot_ad102.bin": "45d6335a8185d6ff13e8d1484cea73f68d3d13aa1c19dc080ed1c3482dd5bac0",
    "gsp_boot_desc_ad102.bin": "83f8f3f1f5f9496e0ea8fc7103c2beb64d0b6de2f5ffe725f13514de5a95fa42",
    "gsp_ga10x.bin": "572373620a37418f24dc16b5031c39338778c3257e48e8408de9a57291b24f3a",
    "v67-ad102-610.43.03-four-plm.bin": "44c36b2d6b3424e53e18f3e55db85c833655de071ce66ce42749588a4a7dc8cb",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(cache: Path, verbose: bool = True) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, spec in SOURCES.items():
        dest = cache / name
        if dest.exists() and sha256(dest) == spec["sha256"]:
            if verbose:
                print(f"cached  {name} ({dest.stat().st_size} bytes)")
        else:
            if verbose:
                print(f"fetch   {name}")
                print(f"        {spec['url']}")
            req = urllib.request.Request(spec["url"], headers={"User-Agent": "gpu-unlock-ad104/1.0"})
            with urllib.request.urlopen(req, timeout=1800) as r, dest.open("wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            got = sha256(dest)
            if got != spec["sha256"]:
                sys.exit(f"sha256 mismatch for {name}\n  expected {spec['sha256']}\n  got      {got}")
            if verbose:
                print(f"ok      {name} ({dest.stat().st_size} bytes)")
        paths[name] = dest
    return paths


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=ROOT / "downloads")
    ap.add_argument("--assets", type=Path, default=ROOT / "build" / "assets")
    ap.add_argument("--verify-only", action="store_true")
    a = ap.parse_args()

    src = a.cache / "NVIDIA-kernel-module-source-610.43.03.tar.xz"
    pkg = a.cache / "nvidia-utils-610.43.03-1-x86_64_v3.pkg.tar.zst"
    if not a.verify_only:
        paths = fetch(a.cache)
        src, pkg = paths[src.name], paths[pkg.name]
    else:
        for p in (src, pkg):
            if not p.exists():
                sys.exit(f"missing cache entry: {p} (drop --verify-only to download)")

    a.assets.mkdir(parents=True, exist_ok=True)

    print("\nextract boot assets from the NVIDIA source archive")
    subprocess.run([sys.executable, str(FW / "extract_boot_assets.py"),
                    str(src), str(a.assets), "--arch", "ad102"], check=True)

    print("\nextract gsp_ga10x.bin from the nvidia-utils package")
    subprocess.run([sys.executable, str(ROOT / "tools" / "extract_gsp.py"),
                    str(pkg), str(a.assets)], check=True)

    print("\nderive the four-PLM payload")
    subprocess.run([sys.executable, str(ROOT / "tools" / "gen_payload.py"),
                    "--out", str(a.assets / "v67-ad102-610.43.03-four-plm.bin")], check=True)

    print("\nverify")
    bad = 0
    for name, want in ASSETS.items():
        p = a.assets / name
        if not p.exists():
            print(f"  MISSING {name}")
            bad += 1
            continue
        got = sha256(p)
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name:38s} {p.stat().st_size:>10} bytes")
    if bad:
        return 1
    print(f"\nall assets ready in {a.assets}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
