# Installed CLI acceptance

Result: **PASS** from the clean installed wheel outside the source tree.

- `dmf prices validate`: `ENGINEERING_READY`, `production_actionable=false`.
- `dmf prices simulate-path --input <synthetic fixture>`: 2187 exact seven-update paths.
- Distribution SHA-256:
  `1f44f7d3f3b84ad77bf39db65ed30761cb029070c1ddaf6643019d77e5bc41da`.
- CLI/service equivalence tests cover every implemented Stage-13 command.
- Malformed, missing and contract-invalid inputs return typed machine-readable failures.
