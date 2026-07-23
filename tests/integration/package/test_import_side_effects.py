"""Import the complete package with external-effect boundaries booby-trapped."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


@pytest.mark.integration
def test_all_package_modules_import_without_external_effects() -> None:
    script = r"""
import asyncio
import builtins
import logging
import logging.config
import os
import pathlib
import pkgutil
import socket
import subprocess
import tempfile
import sqlalchemy

os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
environment_before = dict(os.environ)
root_logger = logging.getLogger()
logging_before = (tuple(root_logger.handlers), root_logger.level, root_logger.disabled, tuple(root_logger.filters))

def blocked(*args, **kwargs):
    raise AssertionError('external effect during import')

original_open = builtins.open
original_os_open = os.open

def guarded_open(file, mode='r', *args, **kwargs):
    if any(flag in mode for flag in ('w', 'a', 'x', '+')):
        blocked()
    return original_open(file, mode, *args, **kwargs)

def guarded_os_open(path, flags, *args, **kwargs):
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    if flags & write_flags:
        blocked()
    return original_os_open(path, flags, *args, **kwargs)

socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.gethostbyname = blocked
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.socket.sendto = blocked
subprocess.Popen = blocked
subprocess.run = blocked
builtins.open = guarded_open
os.open = guarded_os_open
os.mkdir = blocked
os.makedirs = blocked
os.putenv = blocked
os.remove = blocked
os.unlink = blocked
os.unsetenv = blocked
pathlib.Path.write_text = blocked
pathlib.Path.write_bytes = blocked
pathlib.Path.mkdir = blocked
pathlib.Path.touch = blocked
tempfile.NamedTemporaryFile = blocked
tempfile.TemporaryDirectory = blocked
tempfile.mkdtemp = blocked
tempfile.mkstemp = blocked
logging.basicConfig = blocked
logging.config.dictConfig = blocked
logging.config.fileConfig = blocked

import dmf_pulse
for module in pkgutil.walk_packages(dmf_pulse.__path__, dmf_pulse.__name__ + '.'):
    __import__(module.name)
assert dict(os.environ) == environment_before
logging_after = (tuple(root_logger.handlers), root_logger.level, root_logger.disabled, tuple(root_logger.filters))
assert logging_after == logging_before
print('IMPORT_OK')
"""
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "IMPORT_OK"
