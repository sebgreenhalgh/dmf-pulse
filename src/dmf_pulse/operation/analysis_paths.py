"""Explicit private analytical storage setup; no import-time effects."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path


def warehouse_path() -> Path:
    if os.name != "nt":
        configured = os.environ.get("XDG_DATA_HOME")
        base = Path(configured) if configured else Path.home() / ".local" / "share"
        if not base.is_absolute():
            raise ValueError("ANALYSIS_ABSOLUTE_DATA_PATH_REQUIRED")
        return base / "dmf-pulse" / "analysis" / "dmf_pulse.sqlite"
    from dmf_pulse.operation.local_control import original_installation_root

    return original_installation_root().parent / "analysis" / "dmf_pulse.sqlite"


def protect_owner_path(path: Path) -> None:
    """Protect an existing directory/file for this actual OS user, fail closed."""
    if path.is_symlink() or path.is_junction():
        raise ValueError("ANALYSIS_REPARSE_PATH_REJECTED")
    if os.name != "nt":
        path.chmod(0o700 if path.is_dir() else 0o600)
        return
    loader = ctypes.WinDLL
    kernel = loader("kernel32", use_last_error=True)
    api = loader("advapi32", use_last_error=True)
    pointer = ctypes.c_void_p
    kernel.GetCurrentProcess.restype = pointer
    kernel.CloseHandle.argtypes = [pointer]
    kernel.LocalFree.argtypes = [pointer]
    api.OpenProcessToken.argtypes = [pointer, ctypes.c_uint32, ctypes.POINTER(pointer)]
    api.GetTokenInformation.argtypes = [
        pointer,
        ctypes.c_int,
        pointer,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    api.ConvertSidToStringSidW.argtypes = [pointer, ctypes.POINTER(pointer)]
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(pointer),
        pointer,
    ]
    api.SetFileSecurityW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, pointer]
    token, sid_text, descriptor = pointer(), pointer(), pointer()
    try:
        if not api.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise OSError("ANALYSIS_OWNER_ACL_FAILED")
        size = ctypes.c_uint32()
        api.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not api.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise OSError("ANALYSIS_OWNER_ACL_FAILED")
        sid = ctypes.cast(buffer, ctypes.POINTER(pointer))[0]
        if not api.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise OSError("ANALYSIS_OWNER_ACL_FAILED")
        identity = ctypes.wstring_at(sid_text)
        sddl = f"D:P(A;OICI;FA;;;{identity})"
        if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ) or not api.SetFileSecurityW(str(path), 0x80000004, descriptor):
            raise OSError("ANALYSIS_OWNER_ACL_FAILED")
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid_text:
            kernel.LocalFree(sid_text)
        if token:
            kernel.CloseHandle(token)
