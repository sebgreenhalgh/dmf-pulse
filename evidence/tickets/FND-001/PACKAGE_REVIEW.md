# FND-001 CI and package review

- Package verification: **PASS**; clean environment outside repository: `True`; cleanup: `True`.
- Python: `3.13.9` on `Windows` / `AMD64`.
- uv: `uv 0.11.26 (396ef7ce4 2026-06-30 x86_64-pc-windows-msvc)`; build frontend: `1.5.0`; backend: Hatchling `1.31.0` (isolated backend pinned exactly).
- Installed CLI: `dmf 0.1.0`; installed doctor: `HEALTHY`; installed module: `<temporary-environment>/site-packages/dmf_pulse/__init__.py`.
- Wheel content: `31` files, `py.typed=True`, wheel SHA-256 `f75311b81b07daa2a0fc80a5ba37a21be5e1103158dc8c3daaadda413fc6c641`.
- Bundled Windows timezone fallback was exercised with system TZ paths disabled; TZif SHA-256 `676541f0b8ad457c744c093f807589adcad909e3fd03f901787d08786eedbd33`. This one IANA tzdata 2025b payload is public domain and carved out of the repository proprietary notice.

## Independently built distributions

- `dmf_pulse-0.1.0-py3-none-any.whl` — 36962 bytes — `f75311b81b07daa2a0fc80a5ba37a21be5e1103158dc8c3daaadda413fc6c641`
- `dmf_pulse-0.1.0.tar.gz` — 768271 bytes — `3f23dc2c0314551b0e52eb3f486e386777716c8299c3f9236240cb5af2e1e5d1`

CI uses `contents: read`, checkout without persisted credentials, frozen sync, offline tests/clean-wheel verification after installation, and no production secret. Ubuntu runs on push/PR; the Windows smoke is scheduled/manual to conserve private-repository minutes.
