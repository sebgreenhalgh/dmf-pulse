"""Only the six exact reviewed GW10 private Odds source-policy adapters.

The historical R8A/R8B and ACCEL003/004/005 maps remain unchanged. These
literal bytes were independently reviewed in ac67e3aa6482c69d02fc2ee5d61709036ae99a4943f8078aa9f8f8f8f0f9dec0
and reauthenticated in the compatibility
addendum 7622628db63e49cc3775fc59f2ff515fdbe4c25271fe02d3763f31ef374ff2c0.
No source is learned, normalized, skipped or authorized from current files.
"""

import hashlib

GW10_REVIEWED_SOURCE_SHA256 = {
    "ingestion/odds/client.py": "507f6dd571732ae2e25fd4997be714a6ddc2f8874cfcc5dcc8561d69406c3430",
    "ingestion/odds/current.py": "d04a5e0db9e0f90b60e8306797cdfd224e7b5d88738b6669cb724ccca38e4180",
    "ingestion/odds/identity.py": "8bbef66b1e34f03d0435913f42b669a0dd25335ac1efe82ae2df27c6835b2907",
    "ingestion/odds/transient.py": "e217f3b4b535ed2a63a556a0f78e49a8d411a623ebc6afa38815b9610787fce2",
    "markets/current.py": "849b8b74df6a27f9283c4f94db9f05a8f30e86343d7ade05a2bba8d1341c1231",
    "private_v1/horizon_markets.py": "3138365e7a866da75b2729f5e748cfe91605eef0516d01a08079d638a1f10603",
}


def is_exact_gw10_reviewed_source(relative: str, body: bytes) -> bool:
    """Recognize exact previously reviewed bytes at their one fixed source path."""
    return (
        relative in GW10_REVIEWED_SOURCE_SHA256
        and hashlib.sha256(body).hexdigest() == GW10_REVIEWED_SOURCE_SHA256[relative]
    )
