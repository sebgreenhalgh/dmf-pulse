from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

P = Path(
    r"C:/Users/sebgr/Documents/dmf-pulse-context/CodexPacks/DMF_PULSE_CODEX_PACK_007/MIN_007_FINAL_REVIEW.zip"
)


def main():
    with zipfile.ZipFile(P) as z:
        names = z.namelist()
        assert len(names) == 17 and len(set(names)) == 17
        bad = z.testzip()
        assert bad is None, bad
        m = json.loads(z.read("17_REVIEW_MANIFEST.json"))
        assert m["root_file_count"] == 17
        for n, h in m["files"].items():
            assert hashlib.sha256(z.read(n)).hexdigest() == h
    print("Final review archive: PASS (17 roots, CRC, manifest)")


if __name__ == "__main__":
    main()
