# Permanent private operation

After the one-time reviewed standing installation and owner acceptance, run
`dmf start`, or open the installed `Launch-DMFPulse.ps1` launcher. Keep that
PowerShell window open while using Seb's Desk. Close it before maintenance.

The application reuses valid protected FPL metadata. Otherwise it prompts once
for a newly issued JWT with hidden input and obtains its expiry in memory.
Never send the token through chat, arguments or a file. Reading its expiry does
not verify FPL authentication. The existing protected Odds key is reused.

The launcher recovers the original owner-bound PostgreSQL ledger, checks actual
quota through the separately qualified zero-credit sports endpoint, and derives
the next eligible Gameweek and deadline from official FPL data. It admits one
bounded acquisition only while the standing rights, deadline, quota and budgets
are valid. It reserves two credits for one EPL Odds GET, with no automatic retry.
The dashboard distinguishes reserved credits from actual response-header cost.

Restarting, reloading or pressing Refresh cannot buy another acquisition for
the same account, manager, season and Gameweek. A completed private receipt is
shown as a retained as-of result. An incomplete attempt remains blocked for
audit, including an attempt that stopped before a chargeable request. This is
the conservative one-attempt policy; it does not promise automatic recovery.

Forecasts remain unvalidated. Provider source bodies stay transient; the accepted
private derived recommendations and immutable audit metadata are retained.
Errors show a fixed reason and next action. Quota contradictions or missing
charged-response headers require reconciliation rather than another paid call.

## Reviewed maintenance

Use the installed PowerShell launcher with an independently reviewed, signed,
offline carrier:

```powershell
& "$env:LOCALAPPDATA\DMFPulse\operator\Launch-DMFPulse.ps1" `
  -Action install-reviewed-update -Carrier 'C:\absolute\reviewed-carrier'
```

To restore an already retained release, use `-Action rollback-reviewed-update
-ReleaseId <the reviewed 64-character wheel identity>`. These technical commands
require a closed dashboard and no live canonical execution grants. They retain
the original database and history. They cannot install a replacement owner root
key or change the accepted material policy, numerical package, dependency lock,
dependency inventory or Python platform. Material changes need fresh review and
owner acceptance. Technical review and signatures remain necessary for permitted
compatibility corrections; routine operation requires no hash exchange.

Use `-Action withdraw-standing` to stop future acquisition. Withdrawal cannot
reenroll the application. No automatic update, provider retry, FPL account write
or database downgrade is performed.
