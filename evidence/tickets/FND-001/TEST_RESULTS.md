# FND-001 test results

- Status: **PASS**
- Pytest: **104 passed**, **0 failed**
- Branch coverage: **90.57%** (288/318 branches)
- Hypothesis: `ci (derandomized, database disabled, 75 examples)`
- Isolation: user-home variables are redirected; DNS, TCP, and UDP boundaries are blocked; clean-wheel verification runs with `UV_OFFLINE=1` after frozen sync.
- Import safety: every package module is imported with subprocess, network, environment mutation, logging configuration, filesystem writes, and temporary-file boundaries trapped.
