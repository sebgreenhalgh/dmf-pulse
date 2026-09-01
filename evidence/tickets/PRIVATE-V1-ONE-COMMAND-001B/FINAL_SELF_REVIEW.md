# Adversarial self-review

| Attack | Finding and disposition |
|---|---|
| Swallow all socket errors | Rejected. Only a timeout-adjustment `OSError` on a descriptor proven closed/detached is deferred to `response.read()`; open and unclassifiable socket failures remain fatal. |
| Hide premature body-read failure | Rejected. Genuine `OSError`, `TimeoutError`, `SSLError` and `HTTPException` retain their typed mapping, and clean EOF before declared `Content-Length` fails closed. |
| Remove read or total deadline | None. The remaining total deadline and per-read timeout calculation still occurs before every read. |
| Weaken response ceiling | None. Exact-limit and limit-plus-one tests prove unchanged `PAYLOAD_TOO_LARGE` behavior. |
| Redirect/TLS/allowlist weakening | None. HTTPS host/path and GET invariants are unchanged; redirects and TLS failures remain blocked. |
| Credential disclosure | None. Secret-bearing request failures and body markers are absent from typed errors; real probes use no credentials. |
| Provider response retention | None. Live byte counts only were printed; bodies were not written, cached, backed up or added to evidence. |
| Odds or pipeline redesign | None. No Odds, CLI, assembly, model, scorer, optimiser or report production file changed. |
| Platform-specific workaround | None. The fix uses `fileno()` descriptor state and the stable reader result, with deterministic lifecycle coverage independent of OS. |
| Synthetic success labelled real | No. Offline lifecycle tests, real public reads and the blocked genuine one-command retry are reported separately. |

No unresolved P0/P1 hotfix finding remains. Exact-final-SHA CI, independent review and human
acceptance remain separate and are not claimed here.
