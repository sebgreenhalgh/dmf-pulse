"""Six exact GW10 adapters and one reversible OPR response-header hook.

The historical R8A/R8B and ACCEL003/004/005 maps remain unchanged. These
literal bytes were independently reviewed in ac67e3aa6482c69d02fc2ee5d61709036ae99a4943f8078aa9f8f8f8f0f9dec0
and reauthenticated in the compatibility
addendum 7622628db63e49cc3775fc59f2ff515fdbe4c25271fe02d3763f31ef374ff2c0.
The OPR state is separately pinned and projects to the historical bytes by
removing exactly four authenticated additions. No source state is learned or
authorized from current files.
"""

import hashlib
import json

GW10_REVIEWED_SOURCE_SHA256 = {
    "ingestion/odds/client.py": "507f6dd571732ae2e25fd4997be714a6ddc2f8874cfcc5dcc8561d69406c3430",
    "ingestion/odds/current.py": "d04a5e0db9e0f90b60e8306797cdfd224e7b5d88738b6669cb724ccca38e4180",
    "ingestion/odds/identity.py": "8bbef66b1e34f03d0435913f42b669a0dd25335ac1efe82ae2df27c6835b2907",
    "ingestion/odds/transient.py": "e217f3b4b535ed2a63a556a0f78e49a8d411a623ebc6afa38815b9610787fce2",
    "markets/current.py": "849b8b74df6a27f9283c4f94db9f05a8f30e86343d7ade05a2bba8d1341c1231",
    "private_v1/horizon_markets.py": "3138365e7a866da75b2729f5e748cfe91605eef0516d01a08079d638a1f10603",
}

# OPR-001 records actual paid-response headers before response-body parsing.
# This separate exact state does not replace any historical GW10 map entry.
OPR_REVIEWED_SOURCE_SHA256 = {
    "ingestion/odds/client.py": "8b3d3193ffb142bc678f4730299eebd82d3134efdf92dcfe761fa788d7c44a76",
}
_GW10_MAP_SHA256 = "abc829cbb5592e593b820a3add28243402fd3608b2d9b933a2a7a561780e9663"
_OPR_MAP_SHA256 = "37d2e81184e17a1582458d2864ae7a3d434e845f35dd66095dede718355edda0"
_OPR_PARENT_SHA256 = "507f6dd571732ae2e25fd4997be714a6ddc2f8874cfcc5dcc8561d69406c3430"
_OPR_HEADER_HOOK_LINES = (
    b"        on_response_headers: Callable[[int, Mapping[str, str]], None] | None = None,\n",
    b"        self._on_response_headers = on_response_headers\n",
    b"            if self._on_response_headers is not None:\n",
    b"                self._on_response_headers(response.status, headers)\n",
)


def historical_gw10_source_bytes(relative: str, body: bytes) -> bytes | None:
    """Return historical bytes only after whole-file and exact inverse checks."""
    if (
        hashlib.sha256(
            json.dumps(GW10_REVIEWED_SOURCE_SHA256, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != _GW10_MAP_SHA256
    ):
        return None
    digest = hashlib.sha256(body).hexdigest()
    if relative in GW10_REVIEWED_SOURCE_SHA256 and digest == GW10_REVIEWED_SOURCE_SHA256[relative]:
        return body
    if (
        hashlib.sha256(
            json.dumps(OPR_REVIEWED_SOURCE_SHA256, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != _OPR_MAP_SHA256
    ):
        return None
    if relative != "ingestion/odds/client.py" or digest != OPR_REVIEWED_SOURCE_SHA256.get(relative):
        return None
    if GW10_REVIEWED_SOURCE_SHA256[relative] != _OPR_PARENT_SHA256:
        return None
    projected = body
    for line in _OPR_HEADER_HOOK_LINES:
        if projected.count(line) != 1:
            return None
        projected = projected.replace(line, b"", 1)
    if hashlib.sha256(projected).hexdigest() != _OPR_PARENT_SHA256:
        return None
    return projected


def is_exact_gw10_reviewed_source(relative: str, body: bytes) -> bool:
    """Recognize historical GW10 bytes or the exact reversible OPR hook state."""
    return historical_gw10_source_bytes(relative, body) is not None
