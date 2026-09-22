"""Test-only process-local write denial; generated data, never live credentials."""

import builtins
import io
import os
from contextlib import contextmanager

import pytest


@contextmanager
def deny_writes():
    open_builtin, open_io, open_os = builtins.open, io.open, os.open

    def checked_open(delegate, file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError("private observation attempted filesystem write")
        return delegate(file, mode, *args, **kwargs)

    def checked_os_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise AssertionError("private observation attempted filesystem write")
        return open_os(path, flags, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            builtins, "open", lambda *args, **kwargs: checked_open(open_builtin, *args, **kwargs)
        )
        patch.setattr(io, "open", lambda *args, **kwargs: checked_open(open_io, *args, **kwargs))
        patch.setattr(os, "open", checked_os_open)
        yield
