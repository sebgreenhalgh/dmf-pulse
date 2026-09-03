# PRIVATE-V1-ONE-COMMAND-001N command ledger

All commands ran from isolated worktree `review_pack/one-command-n` on the required branch. The
unrelated dirty root worktree was not modified. No credential, private entry ID, provider body, or
private manager state is recorded.

| Gate | Result |
|---|---|
| Parent/worktree | PASS; exact immutable parent `ad155c077253a0525f0c7406e955240146823f80` |
| Parent exact-SHA CI | PASS; GitHub Actions run `33704284462` |
| Authority | PASS; A10/A11/B2/B4 manifest scopes, controlling DMFP decisions/specifications, OPT-010/011, and 001K/001L/001M reviewed |
| Focused final rolling contracts/services | PASS; 30 tests in 65.65 seconds |
| Final one-command affected suite | PASS; 8 tests in 176.22 seconds |
| Full private-v1 plus CLI replay | PASS; 124 tests in 326.12 seconds |
| Full Stage-11 unit/golden/property/contract matrix | PASS; 320 tests in 382.80 seconds |
| Final branch-instrumented affected matrix | PASS; 445 tests in 1,148.30 seconds |
| Touched-module coverage | PASS; 90.6127% aggregate statement/branch score, 93.5523% statements and 80.9145% branch arcs; unchanged 90% aggregate gate |
| Exact-small independent oracle | PASS; root action, full-horizon utility, FT/hit/bank/squad recourse, and zero terminal match the independent exhaustive oracle |
| FT carry/opposite/hit proofs | PASS; rolling root can retain the second FT to avoid a real future hit, spend both when immediate gain clears recourse, and take a rational compiled hit |
| One-GW compatibility | PASS; unchanged one-GW execution input equality, bytes, and semantic hash; all inherited frozen Stage-11 hashes pass |
| Determinism/nonanticipativity | PASS; order/tie tests plus accepted scenario-tree nonanticipativity tests; private three-node topology reveals no new information |
| Synthetic benchmark | PASS; 132.10-second case wall clock and 125.028-second instrumented-stage total |
| Ruff format/lint | PASS; 758 files formatted, zero lint findings |
| Strict mypy | PASS; zero issues in 284 source files |
| Frozen sync | PASS; 40 packages checked and unchanged |
| Build | PASS; sdist and `dmf_pulse-0.2.0-py3-none-any.whl` built |
| Clean installed wheel | PASS; locked offline runtime sync outside the source tree, wheel install, rolling public imports, `dmf 0.2.0`, and installed `pulse --help` horizon option |
| Generic wheel verifier | BLOCKED only at its database phase because local `DMF_TEST_DATABASE_URL` is absent; the gate was not weakened or bypassed |
| Local generated launcher | Windows application-control blocked the disposable `dmf.exe`; the verifier-approved importlib entry-point invocation passed from the installed wheel |
| Repository/ticket manifest/secret validation | PASS after final manifest generation; zero secret findings |
| Exact final-SHA CI | Candidate runs `33720824173` and `33722714830` exposed one ANSI-colour-sensitive help assertion after 606 passing shard tests; Typer-normalized test remediation verified locally, replacement exact-SHA run pending |
| Optional private live run | Not attempted before exact-SHA CI, as required |

The first broad coverage pass exposed an 87.73% aggregate rather than a test failure. Additional
hostile contract and CLI boundary proofs raised the preliminary source to 90.03%. After the final
authority correction that removed a redundant literal rolling transfer ceiling, the clean final
coverage run passed at 90.60%. No exclusion, threshold, dependency, or source gate was changed.

The first build invocation was attempted concurrently with another `uv` process and Windows denied
that executable start. The same installed `uv.exe` succeeded serially, and the complete final gate
was rerun serially. An initial repository validation correctly reported the active manifest stale;
an initial secret scan flagged a repository-owned synthetic credential literal. A first
remediation still used a sensitive-named variable and was correctly rejected; the final indirect
neutral marker passed with zero findings.

The first candidate exact-SHA workflow registered the rolling option correctly and passed
pre-flight, but GitHub's forced ANSI styling split the raw help text consumed by one assertion.
An explicit uncoloured test invocation passed locally, including with CI/forced-colour environment
signals, but the second candidate confirmed that GitHub's Rich renderer bypasses that request. The
assertions now normalize the captured stream with Typer's pinned ANSI stripper while retaining the
independent exact option-set contract.

The final implementation SHA is necessarily reported out of band because embedding a commit's own
hash in its contents is self-referential. Exact-SHA CI is recorded in the completion handoff after
the immutable implementation commit is pushed.
