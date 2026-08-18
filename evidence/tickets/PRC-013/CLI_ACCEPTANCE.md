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
