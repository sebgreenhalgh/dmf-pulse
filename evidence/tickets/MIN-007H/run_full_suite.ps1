$ErrorActionPreference = 'Continue'
$env:DMF_ENVIRONMENT = 'TEST'
$env:PGPASSWORD = 'changeme'
$env:DMF_TEST_DATABASE_URL = 'postgresql+psycopg://dmf_test@127.0.0.1:55432/dmf_pulse_test'
cmd.exe /c "uv run pytest -q --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/MIN-007H/coverage.json --cov-fail-under=90" *> evidence/tickets/MIN-007H/full_test_output.txt
$code = $LASTEXITCODE
Set-Content -LiteralPath evidence/tickets/MIN-007H/full_test_exit.txt -Value ([string]$code) -Encoding utf8
exit $code
