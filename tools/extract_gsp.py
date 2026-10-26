#!/usr/bin/env python3
"""Extract gsp_ga10x.bin from the pinned nvidia-utils package without zstd.exe.

Python 3.14 can decompress zstd natively (PEP 784), so the upstream helper's
external `zstd -dc` dependency is replaced by a stdlib stream here.
"""
import hashlib
import sys
import tarfile
from pathlib import Path

GSP_SHA256 = "572373620a37418f24dc16b5031c39338778c3257e48e8408de9a57291b24f3a"
MEMBER = "usr/lib/firmware/nvidia/610.43.03/gsp_ga10x.bin"


def main() -> int:
    pkg = Path(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    target = out / "gsp_ga10x.bin"

    with tarfile.open(pkg, "r:zst") as archive:  # type: ignore[arg-type]
        member = archive.getmember(MEMBER)
        if not member.isfile():
            sys.exit("member is not a regular file")
        stream = archive.extractfile(member)
        if stream is None:
            sys.exit("cannot read member")
        data = stream.read()

    digest = hashlib.sha256(data).hexdigest()
    if digest != GSP_SHA256:
        sys.exit(f"gsp hash mismatch: {digest}")
    target.write_bytes(data)
    print(f"{target}: {len(data)} bytes sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
