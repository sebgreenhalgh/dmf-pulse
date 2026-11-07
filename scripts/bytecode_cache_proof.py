"""Read-only proof that flat, exclusively owned bytecode caches are recreatable."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import marshal
import re
import sys
import time
from pathlib import Path

MAX_FILE_BYTES = 2 * 1024 * 1024
CACHE_NAME = re.compile(
    rf"^(.+)\.{re.escape(str(sys.implementation.cache_tag))}(?:\.opt-([12]))?\.pyc$"
)


def _plain(path: Path) -> None:
    if (
        path.is_symlink()
        or path.is_junction()
        or getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400
    ):
        raise ValueError("REPARSE_POINT")


def prove_cache(cache: Path) -> dict[str, object]:
    cache = cache.absolute()
    if cache.name != "__pycache__":
        raise ValueError("CACHE_DIRECTORY_REQUIRED")
    for ancestor in (cache, *cache.parents):
        _plain(ancestor)
    children = sorted(cache.iterdir())
    if not children:
        raise ValueError("EMPTY_CACHE")
    files = []
    total = 0
    for path in children:
        _plain(path)
        match = CACHE_NAME.fullmatch(path.name)
        if not match or not path.is_file():
            raise ValueError("FLAT_CURRENT_ABI_BYTECODE_ONLY")
        state = path.stat(follow_symlinks=False)
        if state.st_nlink != 1 or state.st_size > MAX_FILE_BYTES:
            raise ValueError("EXCLUSIVE_BOUNDED_CACHE_REQUIRED")
        source = cache.parent / (match.group(1) + ".py")
        _plain(source)
        if not source.is_file() or source.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("RETAINED_BOUNDED_SOURCE_REQUIRED")
        body = path.read_bytes()
        if (
            len(body) < 16
            or body[:4] != importlib.util.MAGIC_NUMBER
            or int.from_bytes(body[4:8], "little") not in {0, 1, 3}
        ):
            raise ValueError("BYTECODE_HEADER_INVALID")
        source_bytes = source.read_bytes()
        source_state = source.stat(follow_symlinks=False)
        optimize = int(match.group(2) or "0")
        filename = None
        started = time.perf_counter()
        for spelling in dict.fromkeys((str(source), source.as_posix())):
            code = compile(source_bytes, spelling, "exec", dont_inherit=True, optimize=optimize)
            if marshal.dumps(code) == body[16:]:
                filename = spelling
                break
        if filename is None or time.perf_counter() - started > 2:
            raise ValueError("COMPLETE_BODY_NOT_REPRODUCED_WITHIN_BUDGET")
        _plain(source)
        current_source = source.stat(follow_symlinks=False)
        if source.read_bytes() != source_bytes or (
            current_source.st_dev,
            current_source.st_ino,
            current_source.st_size,
            current_source.st_mtime_ns,
            current_source.st_nlink,
        ) != (
            source_state.st_dev,
            source_state.st_ino,
            source_state.st_size,
            source_state.st_mtime_ns,
            source_state.st_nlink,
        ):
            raise ValueError("SOURCE_CHANGED_DURING_PROOF")
        after = path.stat(follow_symlinks=False)
        if (state.st_ino, state.st_size, state.st_mtime_ns, state.st_nlink) != (
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_nlink,
        ):
            raise ValueError("CACHE_CHANGED_DURING_PROOF")
        files.append(
            {
                "name": path.name,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "source": str(source),
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "compile_filename": filename,
                "optimization": optimize,
                "header_hex": body[:16].hex(),
                "device": str(state.st_dev),
                "inode": str(state.st_ino),
                "mtime_ns": str(state.st_mtime_ns),
                "nlink": 1,
            }
        )
        total += len(body)
    if sorted(cache.iterdir()) != children:
        raise ValueError("CACHE_MEMBERSHIP_CHANGED_DURING_PROOF")
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {
        "status": "PROVEN_RECREATABLE_CACHE",
        "path": str(cache),
        "bytes": total,
        "files": files,
        "proof_sha256": hashlib.sha256(encoded).hexdigest(),
        "interpreter": sys.version,
        "magic_hex": importlib.util.MAGIC_NUMBER.hex(),
        "source_executed_or_bytecode_loaded": False,
    }


def verify_relocated_cache(receipt: dict[str, object], destination: Path) -> None:
    """Verify a literal move against its proof without loading code or changing ACLs."""
    for ancestor in (destination.absolute(), *destination.absolute().parents):
        _plain(ancestor)
    files = receipt["files"]
    if not isinstance(files, list) or sorted(path.name for path in destination.iterdir()) != sorted(
        item["name"] for item in files
    ):
        raise ValueError("RELOCATED_MEMBERSHIP_CHANGED")
    for item in files:
        path = destination / item["name"]
        _plain(path)
        state = path.stat(follow_symlinks=False)
        if (
            not path.is_file()
            or state.st_nlink != 1
            or str(state.st_dev) != item["device"]
            or str(state.st_ino) != item["inode"]
            or str(state.st_mtime_ns) != item["mtime_ns"]
            or state.st_size != item["bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError("RELOCATED_CACHE_CHANGED")
        source = Path(item["source"])
        for ancestor in (source, *source.parents):
            _plain(ancestor)
        if hashlib.sha256(source.read_bytes()).hexdigest() != item["source_sha256"]:
            raise ValueError("RETAINED_SOURCE_CHANGED")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    args = parser.parse_args()
    try:
        result = prove_cache(args.cache)
    except Exception as error:
        print(json.dumps({"status": "HOLD", "exception_family": type(error).__name__}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
