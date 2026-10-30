"""Credential syntax errors must never echo an accidentally supplied secret."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from typer._click.core import Command, Context
from typer._click.exceptions import UsageError
from typer.core import TyperCommand, TyperGroup

_MESSAGE = "Credential command arguments are invalid. Enter values only at the hidden prompt."


@dataclass(frozen=True, slots=True, repr=False)
class _ParseResult:
    value: object = None
    failed: bool = False


def _scope(
    method: Callable[[Context, list[str]], object], ctx: Context, args: list[str]
) -> _ParseResult:
    try:
        return _ParseResult(method(ctx, args))
    except UsageError:
        return _ParseResult(failed=True)


class CredentialCommand(TyperCommand):
    def parse_args(self, ctx: Context, args: list[str]) -> list[str]:
        result = _scope(super().parse_args, ctx, args)
        del self, ctx, args
        if result.failed:
            raise UsageError(_MESSAGE) from None
        return cast(list[str], result.value)


class CredentialGroup(TyperGroup):
    def parse_args(self, ctx: Context, args: list[str]) -> list[str]:
        result = _scope(super().parse_args, ctx, args)
        del self, ctx, args
        if result.failed:
            raise UsageError(_MESSAGE) from None
        return cast(list[str], result.value)

    def resolve_command(
        self, ctx: Context, args: list[str]
    ) -> tuple[str | None, Command | None, list[str]]:
        result = _scope(super().resolve_command, ctx, args)
        del self, ctx, args
        if result.failed:
            raise UsageError(_MESSAGE) from None
        return cast(tuple[str | None, Command | None, list[str]], result.value)
