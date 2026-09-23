"""Explicit internal control flow for prepared rolling-runner experiments.

These signals are not input-validation errors and must cross the ordinary
one-command sanitisation boundary unchanged. They never carry provider payloads.
"""


class PreparedRollingControlFlow(Exception):
    """Typed internal signal emitted by an approved prepared rolling runner."""


__all__ = ["PreparedRollingControlFlow"]
