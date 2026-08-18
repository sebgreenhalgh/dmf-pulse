# Installed CLI acceptance

Result: **PASS WITH ENVIRONMENT LIMITATION** from the clean installed wheel outside the source tree.

- Installed application version: `dmf 0.2.0`.
- All ten `dmf prices` commands were present: update cycles, features, training, prediction, path
  simulation, selling value, optimiser scenarios, ACT/WAIT, evaluation and validation.
- Validation returned `ENGINEERING_READY`, `production_actionable=false` and
  `parameter_status=PROVISIONAL_MODEL_PARAMETER`.
- Synthetic path simulation returned 2187 exact seven-update paths with distribution SHA-256
  `4b6c41cd90fb91efb0a9ac9b41daf1b65bf63fcce33da19ae54849c4a9e08ad6`.
- CLI/service equivalence tests cover every Stage-13 command; invalid inputs remain typed failures.

Windows Application Control blocked the generated temp-directory `dmf.exe` launcher. The same
installed Typer entry point was therefore invoked with the clean environment's Python process; the
package path proved it came from external `site-packages`, and `PYTHONPATH` was removed.

## Final main integration

The integrated wheel's identical installed Typer entry point passed:

- `dmf 0.2.0`;
- current rules show: `fpl-2026-27`, `VERIFIED`, hash
  `c2883ad9bf1497dad9c2eba69422e14937ddc072f9b3a95c5005a312c38f7d56`;
- `dmf prices validate`: `ENGINEERING_READY`, `production_actionable=false`, configuration hash
  `ee85b46dbe81f9bbee8948b833938e6785965db3927ff7f8d4b4bf1dfc495126`;
- `dmf prices simulate-path`: 2187 paths, distribution SHA-256
  `4b6c41cd90fb91efb0a9ac9b41daf1b65bf63fcce33da19ae54849c4a9e08ad6`;
- `dmf prices act-or-wait`: `WAIT_FOR_INFORMATION`, actionable for the synthetic reconstructed
  acceptance payload, decision SHA-256
  `c69186988e37d1b11d9d9ee76dad482e2b13654b34f521c6ad91774f449b012e`.
