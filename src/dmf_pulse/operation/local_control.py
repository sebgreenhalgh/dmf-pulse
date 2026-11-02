"""Recover the original owner-bound SSPI cluster using reviewed recovery code.

Historical code supplies cluster custody only; expired pilot windows grant no
current source authority. Recovery never initializes or substitutes a ledger.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import types
from pathlib import Path

from dmf_pulse.operation.models import OperationError
from dmf_pulse.operation.standing import StandingPolicy

RECOVERY_CODE_SHA256 = "ae7d00de7d7231b598ee5caf53e63f8ca2791df97f00f4cb3431fd11b3fe3e4a"
ORIGINAL_CONTROL_PROOF_SHA256 = "162da9a511f35cadfe09080d107cb4ee866223ffc4b56b6c0c2c37af146d598f"


def original_installation_root() -> Path:
    if os.name != "nt":
        raise OperationError("ORIGINAL_CONTROL_REQUIRES_OWNER_WINDOWS_SSPI_SESSION")
    function = ctypes.WinDLL("shell32").SHGetFolderPathW
    function.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
    ]
    function.restype = ctypes.c_long
    buffer = ctypes.create_unicode_buffer(32768)
    if function(None, 0x001C, None, 0, buffer) != 0:
        raise OperationError("OWNER_LOCAL_APPLICATION_FOLDER_UNAVAILABLE")
    return Path(buffer.value) / "DMFPulse" / "gw10"


def recover_local_control(policy: StandingPolicy) -> None:
    try:
        root = original_installation_root()
        path = root / "launch_operator.py"
        # Execute exactly the verified buffer, bypassing timestamp bytecode.
        with path.open("rb") as stream:
            body = stream.read(131073)
        if len(body) > 131072 or hashlib.sha256(body).hexdigest() != RECOVERY_CODE_SHA256:
            raise OperationError("ORIGINAL_CONTROL_RECOVERY_CODE_CHANGED")
        helper = types.ModuleType("_reviewed_original_control_recovery")
        helper.__file__ = str(path)
        exec(compile(body, str(path), "exec"), helper.__dict__)
        helper.regular(path)
        helper.recover_canonical(
            root,
            {"ledger_id": policy.ledger_id, "control_actual_sha256": ORIGINAL_CONTROL_PROOF_SHA256},
            types.SimpleNamespace(
                ledger_id=policy.ledger_id,
                operator_ref=policy.owner_ref,
                plan_quota=types.SimpleNamespace(account_ref=policy.odds_account_ref),
            ),
        )
    except OperationError:
        raise
    except Exception:
        raise OperationError("ORIGINAL_SSPI_CONTROL_RECOVERY_FAILED") from None
