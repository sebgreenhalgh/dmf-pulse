"""Minimal transport-neutral provider-adapter boundary."""

from __future__ import annotations

from typing import Protocol, TypeVar

ResourceT = TypeVar("ResourceT", contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)


class ProviderAdapter(Protocol[ResourceT, ResultT]):
    """Validate supplied bytes and, when separately authorized, fetch a resource."""

    provider_key: str
    adapter_version: str
    contract_version: str

    def validate(self, resource: ResourceT, body: bytes) -> ResultT: ...

    def fetch(self, resource: ResourceT) -> bytes: ...


__all__ = ["ProviderAdapter"]
