# Bundled Europe/London zone data

`Europe/London` is bundled solely as the default IANA validation fallback for stock Windows
Python 3.13, whose standard-library `zoneinfo` may have no system database. The TZif payload is
from IANA tzdata 2025b distributed with the development Python installation; `tzdata.zi` states
that its input is public domain. Its required SHA-256 is
`676541f0b8ad457c744c093f807589adcad909e3fd03f901787d08786eedbd33`.

The standard-library search path remains authoritative when available. No timezone package or
network lookup is added, and the repository secret scanner skips this exact binary only when its
hash matches.
