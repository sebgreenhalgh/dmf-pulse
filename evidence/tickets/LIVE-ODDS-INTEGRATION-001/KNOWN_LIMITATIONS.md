# LIVE-ODDS-INTEGRATION-001 known limitations

- The integration merge commit cannot embed its own future SHA without a forbidden post-merge
  evidence commit; its exact parents and final identity are externally reported.
- Automatic final-SHA CI is necessarily pending until the one merge commit is pushed. The branch is
  not changed after successful CI merely to record its run ID.
- This engineering work does not independently review or human-accept the integration.
- This ticket does not create a replacement PR, merge to main, close PR #16, or activate production.
- Existing LIVE-ODDS human acceptance remains bound only to `5e55cf...`.
