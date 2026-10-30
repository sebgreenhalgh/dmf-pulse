"""Installed Windows acceptance on one fresh synthetic target; never production."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=("create", "resolve", "rotate", "resolve-rotated", "delete", "absent"),
        required=True,
    )
    parser.add_argument("--namespace", required=True)
    args = parser.parse_args()
    if os.name != "nt" or not re.fullmatch(
        r"dmf-pulse/acceptance/ACCEL004/[0-9a-f]{32}", args.namespace
    ):
        raise SystemExit("owned Windows acceptance namespace required")

    from typer.testing import CliRunner

    import dmf_pulse
    from dmf_pulse.cli import credentials as cli
    from dmf_pulse.cli.app import app
    from dmf_pulse.credentials.providers import AutomaticOddsCredentialProvider
    from dmf_pulse.credentials.service import CredentialService
    from dmf_pulse.credentials.windows import WindowsCredentialBackend
    from dmf_pulse.dashboard.current import implementation_fingerprint

    package = Path(dmf_pulse.__file__).resolve()
    if "site-packages" not in package.parts:
        raise SystemExit("clean installed wheel required")
    backend = WindowsCredentialBackend(namespace=args.namespace)
    service = CredentialService(lambda: backend)
    suffix = ":rotated" if args.phase in {"rotate", "resolve-rotated"} else ""
    value = hashlib.sha256(
        ("owned-ACCEL004-native-acceptance:" + args.namespace + suffix).encode()
    ).hexdigest()
    cli._service = lambda: service
    if args.phase == "create":
        assert not service.status("odds").configured
        result = CliRunner().invoke(app, ["credentials", "set-odds-key"], input=value + "\n")
        assert result.exit_code == 0 and value not in result.output
        assert service.status("odds").configured
    elif args.phase == "rotate":
        result = CliRunner().invoke(
            app, ["credentials", "set-odds-key", "--replace"], input=value + "\n"
        )
        assert result.exit_code == 0 and value not in result.output
    elif args.phase in {"resolve", "resolve-rotated"}:
        provider = AutomaticOddsCredentialProvider(
            service_factory=lambda: CredentialService(lambda: backend), environment={}
        )
        assert provider.get_credential() == value
    elif args.phase == "delete":
        result = CliRunner().invoke(app, ["credentials", "delete-odds-key"])
        assert result.exit_code == 0 and value not in result.output
        assert not service.status("odds").configured
    else:
        assert not service.status("odds").configured
    del value
    from win32ctypes import core

    print(
        json.dumps(
            {
                "status": "PASS",
                "phase": args.phase,
                "pid": os.getpid(),
                "observed_at": datetime.now(UTC).isoformat(),
                "installed_package": str(package),
                "implementation_sha": implementation_fingerprint(),
                "provider_requests": 0,
                "production_targets_read": 0,
                "secret_values_recorded": False,
                "binding_version": importlib.metadata.version("pywin32-ctypes"),
                "binding_backend": core._backend,
                "input_boundary": "TYPER_HIDDEN_PROMPT_WITH_OWNED_IN_MEMORY_INPUT_SHIM",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
