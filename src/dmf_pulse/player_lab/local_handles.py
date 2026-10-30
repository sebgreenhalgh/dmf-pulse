"""Handle-relative bounded recovery; path replacements cannot redirect a read."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self


def _posix_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int) or isinstance(value, bool):
        raise OSError("platform lacks safe relative directory access")
    return value


@dataclass(frozen=True)
class LocalEntry:
    name: str
    attributes: int

    def is_dir(self, *, follow_symlinks: bool = False) -> bool:
        del follow_symlinks
        return bool(self.attributes & 0x10)

    def is_file(self, *, follow_symlinks: bool = False) -> bool:
        del follow_symlinks
        return not self.is_dir()


class _WindowsHandles:
    """Lazy native directory enumeration and NtCreateFile relative opens."""

    def __init__(self, stack: ExitStack) -> None:
        import ctypes
        from ctypes import wintypes

        class UnicodeString(ctypes.Structure):
            _fields_ = [
                ("Length", wintypes.USHORT),
                ("MaximumLength", wintypes.USHORT),
                ("Buffer", ctypes.c_void_p),
            ]

        class ObjectAttributes(ctypes.Structure):
            _fields_ = [
                ("Length", wintypes.ULONG),
                ("RootDirectory", wintypes.HANDLE),
                ("ObjectName", ctypes.POINTER(UnicodeString)),
                ("Attributes", wintypes.ULONG),
                ("SecurityDescriptor", ctypes.c_void_p),
                ("SecurityQualityOfService", ctypes.c_void_p),
            ]

        class IoStatus(ctypes.Structure):
            _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

        class DirectoryInfo(ctypes.Structure):
            _fields_ = [
                ("NextEntryOffset", wintypes.DWORD),
                ("FileIndex", wintypes.DWORD),
                ("CreationTime", ctypes.c_longlong),
                ("LastAccessTime", ctypes.c_longlong),
                ("LastWriteTime", ctypes.c_longlong),
                ("ChangeTime", ctypes.c_longlong),
                ("EndOfFile", ctypes.c_longlong),
                ("AllocationSize", ctypes.c_longlong),
                ("FileAttributes", wintypes.DWORD),
                ("FileNameLength", wintypes.DWORD),
                ("EaSize", wintypes.DWORD),
                ("ShortNameLength", ctypes.c_byte),
                ("ShortName", wintypes.WCHAR * 12),
                ("FileId", ctypes.c_longlong),
                ("FileName", wintypes.WCHAR * 1),
            ]

        self._ct = ctypes
        self._wt = wintypes
        self._unicode = UnicodeString
        self._objects = ObjectAttributes
        self._io = IoStatus
        self._directory = DirectoryInfo
        self._stack = stack
        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:
            raise OSError("native Windows directory binding unavailable")
        self._kernel = loader("kernel32", use_last_error=True)
        self._nt = loader("ntdll", use_last_error=True)
        self._kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self._kernel.CreateFileW.restype = wintypes.HANDLE
        self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel.CloseHandle.restype = wintypes.BOOL
        self._kernel.GetFileInformationByHandleEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self._kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
        self._nt.NtCreateFile.argtypes = [
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            ctypes.POINTER(ObjectAttributes),
            ctypes.POINTER(IoStatus),
            ctypes.c_void_p,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            ctypes.c_void_p,
            wintypes.ULONG,
        ]
        self._nt.NtCreateFile.restype = ctypes.c_long

    def open(self, path: Path, parent: int | None, *, directory: bool) -> int:
        from importlib import import_module

        msvcrt = import_module("msvcrt")

        ct, wt = self._ct, self._wt
        access = 0x00100080 | (0x21 if directory else 0x80000000)
        if parent is None:
            handle = self._kernel.CreateFileW(str(path), access, 3, None, 3, 0x02200000, None)
            if handle is None or handle == ct.c_void_p(-1).value:
                raise OSError("approved volume cannot be opened")
        else:
            if (
                not path.name
                or any(value in path.name for value in ("\\", "/", ":", "\x00"))
                or path.name in {".", ".."}
            ):
                raise OSError("invalid relative local name")
            name = ct.create_unicode_buffer(path.name, len(path.name.encode("utf-16-le")) // 2 + 1)
            unicode = self._unicode(
                len(path.name.encode("utf-16-le")), ct.sizeof(name), ct.cast(name, ct.c_void_p)
            )
            attributes = self._objects(
                ct.sizeof(self._objects),
                msvcrt.get_osfhandle(parent),
                ct.pointer(unicode),
                0x40,
                None,
                None,
            )
            output = wt.HANDLE()
            status = self._io()
            result = self._nt.NtCreateFile(
                ct.byref(output),
                access,
                ct.byref(attributes),
                ct.byref(status),
                None,
                0,
                3,
                1,
                0x00200020 | (1 if directory else 0x40),
                None,
                0,
            )
            if result < 0 or output.value is None:
                raise OSError("approved relative local object cannot be opened")
            handle = output.value
        try:
            descriptor = msvcrt.open_osfhandle(
                int(handle), os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
            )
        except OSError:
            self._kernel.CloseHandle(handle)
            raise
        self._stack.callback(os.close, descriptor)
        metadata = os.fstat(descriptor)
        if (
            getattr(metadata, "st_file_attributes", 0) & 0x400
            or stat.S_ISDIR(metadata.st_mode) != directory
        ):
            raise OSError("local link or object type is excluded")
        return int(descriptor)

    def entries(self, descriptor: int) -> Iterator[LocalEntry]:
        from importlib import import_module

        msvcrt = import_module("msvcrt")

        ct = self._ct
        buffer = ct.create_string_buffer(65536)
        first = True
        while True:
            ok = self._kernel.GetFileInformationByHandleEx(
                msvcrt.get_osfhandle(descriptor), 11 if first else 10, buffer, len(buffer)
            )
            first = False
            if not ok:
                if ct.get_last_error() == 18:
                    return
                raise OSError("approved directory cannot be enumerated by handle")
            offset = 0
            while True:
                if offset + self._directory.FileName.offset > len(buffer):
                    raise OSError("invalid directory record bound")
                row = self._directory.from_buffer(buffer, offset)
                end = offset + self._directory.FileName.offset + row.FileNameLength
                if row.FileNameLength % 2 or end > len(buffer):
                    raise OSError("invalid directory name bound")
                name = ct.wstring_at(
                    ct.addressof(buffer) + offset + self._directory.FileName.offset,
                    row.FileNameLength // 2,
                )
                if name not in {".", ".."}:
                    yield LocalEntry(name, row.FileAttributes)
                if row.NextEntryOffset == 0:
                    break
                if (
                    row.NextEntryOffset < self._directory.FileName.offset
                    or offset + row.NextEntryOffset >= len(buffer)
                ):
                    raise OSError("invalid directory continuation")
                offset += row.NextEntryOffset


class DirectoryPins:
    """Hold directories and files; every descendant lookup is relative to a handle."""

    def __init__(self) -> None:
        self._stack = ExitStack()
        self._directories: dict[Path, int] = {}
        self._files: dict[Path, int] = {}
        self._windows: _WindowsHandles | None = None

    def __enter__(self) -> Self:
        self._stack.__enter__()
        if os.name == "nt":
            self._windows = _WindowsHandles(self._stack)
        return self

    def __exit__(self, *args: object) -> None:
        self._stack.close()

    def pin(self, path: Path, *, expected: os.stat_result | None = None) -> int:
        if path in self._directories:
            return self._directories[path]
        parent = None if path.parent == path else self.pin(path.parent)
        if self._windows is not None:
            descriptor = self._windows.open(path, parent, directory=True)
        else:
            flags = os.O_RDONLY | _posix_flag("O_DIRECTORY") | _posix_flag("O_NOFOLLOW")
            descriptor = (
                os.open(path, flags) if parent is None else os.open(path.name, flags, dir_fd=parent)
            )
            self._stack.callback(os.close, descriptor)
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(observed.st_mode)
            or getattr(observed, "st_file_attributes", 0) & 0x400
            or (
                expected is not None
                and (expected.st_dev, expected.st_ino) != (observed.st_dev, observed.st_ino)
            )
        ):
            raise OSError("approved directory identity changed")
        self._directories[path] = descriptor
        return descriptor

    @contextmanager
    def scan(self, path: Path) -> Iterator[Any]:
        descriptor = self.pin(path)
        if self._windows is not None:
            yield self._windows.entries(descriptor)
        else:
            with os.scandir(descriptor) as entries:
                yield entries

    def open_file(self, path: Path) -> int:
        if path in self._files:
            return self._files[path]
        parent = self.pin(path.parent)
        if self._windows is not None:
            descriptor = self._windows.open(path, parent, directory=False)
        else:
            descriptor = os.open(
                path.name,
                os.O_RDONLY | _posix_flag("O_NOFOLLOW") | _posix_flag("O_NONBLOCK"),
                dir_fd=parent,
            )
            self._stack.callback(os.close, descriptor)
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or getattr(observed, "st_file_attributes", 0) & 0x400:
            raise OSError("approved file must be regular")
        self._files[path] = descriptor
        return descriptor

    def metadata(self, path: Path) -> os.stat_result:
        return os.fstat(self.open_file(path))
