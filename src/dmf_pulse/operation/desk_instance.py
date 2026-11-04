"""Owner/process-bound local Desk discovery. No session or provider secrets persist."""

from __future__ import annotations

import ctypes
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from typing import Annotated, Literal

from pydantic import Field

from dmf_pulse.operation.analysis_paths import protect_owner_path
from dmf_pulse.operation.models import Metadata, OperationError, Sha
from dmf_pulse.operation.standing import StandingPolicy


class DeskInstance(Metadata):
    schema_version: Literal["owned-desk-instance-v1"] = "owned-desk-instance-v1"
    pid: Annotated[int, Field(gt=0)]
    creation_ticks: Annotated[int, Field(gt=0)]
    executable: str
    port: Annotated[int, Field(ge=1024, le=65535)]
    implementation_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    ledger_id: Sha
    owner_acceptance_sha256: Sha
    recorded_at: datetime


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class _TcpRow(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint32)
        for name in ("state", "local_address", "local_port", "remote_address", "remote_port", "pid")
    ]


def _listener_pid(port: int) -> int:
    if os.name != "nt":
        raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
    function = getattr(ctypes, "WinDLL")("iphlpapi", use_last_error=True).GetExtendedTcpTable
    function.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_int,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint32,
    ]
    function.restype = ctypes.c_uint32
    size = ctypes.c_uint32()
    status = function(None, ctypes.byref(size), False, 2, 3, 0)
    if status != 122 or not 4 <= size.value <= 2_097_152:
        raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
    buffer = ctypes.create_string_buffer(size.value)
    if function(buffer, ctypes.byref(size), False, 2, 3, 0) != 0:
        raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
    count = ctypes.c_uint32.from_buffer_copy(buffer.raw[:4]).value
    if 4 + count * ctypes.sizeof(_TcpRow) > size.value:
        raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
    rows = [
        _TcpRow.from_buffer_copy(
            buffer.raw[4 + i * ctypes.sizeof(_TcpRow) : 4 + (i + 1) * ctypes.sizeof(_TcpRow)]
        )
        for i in range(count)
    ]
    pids = {
        row.pid
        for row in rows
        if row.state == 2
        and row.local_address == 0x0100007F
        and socket.ntohs(row.local_port & 65535) == port
    }
    if len(pids) != 1:
        raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
    return int(pids.pop())


def _process_identity(pid: int) -> tuple[int, str]:
    """Compare OS token-user SIDs and exact creation identity; read no command line."""
    if os.name != "nt":
        raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
    loader = getattr(ctypes, "WinDLL")
    kernel = loader("kernel32", use_last_error=True)
    api = loader("advapi32", use_last_error=True)
    pointer = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = pointer
    kernel.GetCurrentProcess.restype = pointer
    kernel.CloseHandle.argtypes = [pointer]
    kernel.GetProcessTimes.argtypes = [pointer, *([ctypes.POINTER(_FileTime)] * 4)]
    kernel.QueryFullProcessImageNameW.argtypes = [
        pointer,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    api.OpenProcessToken.argtypes = [pointer, ctypes.c_uint32, ctypes.POINTER(pointer)]
    api.GetTokenInformation.argtypes = [
        pointer,
        ctypes.c_int,
        pointer,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    api.EqualSid.argtypes = [pointer, pointer]
    process = kernel.OpenProcess(0x1000, False, pid)
    if not process:
        raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
    tokens = []
    buffers = []
    sids = []
    try:
        for handle in (kernel.GetCurrentProcess(), process):
            token = pointer()
            if not api.OpenProcessToken(handle, 8, ctypes.byref(token)):
                raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
            tokens.append(token)
            size = ctypes.c_uint32()
            api.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            if not 1 <= size.value <= 65536:
                raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
            buffer = ctypes.create_string_buffer(size.value)
            if not api.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
                raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
            buffers.append(buffer)
            sids.append(ctypes.cast(buffer, ctypes.POINTER(pointer))[0])
        if not api.EqualSid(*sids):
            raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
        created, exited, kernel_time, user_time = (_FileTime() for _ in range(4))
        if not kernel.GetProcessTimes(
            process,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
        size = ctypes.c_uint32(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(process, 0, image, ctypes.byref(size)):
            raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
        return created.low + (created.high << 32), str(Path(image.value).resolve())
    finally:
        for token in tokens:
            kernel.CloseHandle(token)
        kernel.CloseHandle(process)


def _read(path: Path) -> DeskInstance:
    if path.is_symlink() or path.is_junction():
        raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
    with path.open("rb") as stream:
        body = stream.read(8193)
    if len(body) > 8192:
        raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
    return DeskInstance.model_validate_json(body)


def register_instance(path: Path, policy: StandingPolicy, port: int) -> DeskInstance:
    if _listener_pid(port) != os.getpid():
        raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
    birth, image = _process_identity(os.getpid())
    instance = DeskInstance(
        pid=os.getpid(),
        creation_ticks=birth,
        executable=image,
        port=port,
        implementation_sha=policy.implementation_sha,
        ledger_id=policy.ledger_id,
        owner_acceptance_sha256=policy.owner_acceptance_sha256,
        recorded_at=datetime.now(UTC),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    protect_owner_path(path.parent)
    if path.exists() and (path.is_symlink() or path.is_junction()):
        raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
    temporary = path.with_name(f".desk-instance-{os.getpid()}-{token_hex(4)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(instance.model_dump_json())
            stream.flush()
            os.fsync(stream.fileno())
        protect_owner_path(temporary)
        if temporary.parent.resolve() != path.parent.resolve():
            raise OperationError("LOCAL_DASHBOARD_INSTANCE_UNVERIFIED")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return instance


def verified_existing_instance(path: Path, policy: StandingPolicy, port: int) -> bool:
    try:
        instance = _read(path)
        birth, image = _process_identity(instance.pid)
        _, current_image = _process_identity(os.getpid())
        return (
            instance.port == port
            and instance.implementation_sha == policy.implementation_sha
            and instance.ledger_id == policy.ledger_id
            and instance.owner_acceptance_sha256 == policy.owner_acceptance_sha256
            and _listener_pid(port) == instance.pid
            and birth == instance.creation_ticks
            and os.path.normcase(image) == os.path.normcase(instance.executable)
            and os.path.normcase(image) == os.path.normcase(current_image)
        )
    except (OperationError, OSError, ValueError):
        return False


def remove_instance(path: Path, instance: DeskInstance) -> None:
    try:
        current = _read(path)
    except (OSError, ValueError, OperationError):
        return
    if current == instance and current.pid == os.getpid():
        path.unlink()
