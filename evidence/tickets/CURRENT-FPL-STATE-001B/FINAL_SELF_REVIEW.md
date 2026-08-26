# CURRENT-FPL-STATE-001B same-agent final self-review

This is an adversarial implementation-author review. It is not independent review or human
acceptance.

| Severity | Found | Closed | Remaining |
|---|---:|---:|---:|
| P0 | 0 | 0 | 0 |
| P1 | 0 | 0 | 0 |
| Material P2 | 0 | 0 | 0 |
| P3 | 1 | 1 | 0 |

## P0/P1 hostile checks

- Wrong-team and wrong-fixture joins fail closed through exact explicit aliases/bindings, exact
  current catalogue identities and names, exact orientation, exact UTC kickoff, and one-to-one
  complete target coverage.
- No fuzzy, casefolded, punctuation-normalized, abbreviation, truncation, edit-distance, nearest
  event, chronological, code-based, or table-position inference exists.
- Duplicate provider IDs, duplicate FPL fixture IDs, many-to-one mappings, incomplete target
  coverage, multiple exact candidates, and unbound exact target collisions are rejected.
- Source usable times and plan approval times must precede the UTC mapping decision, which must not
  exceed the exact common cutoff. Source cutoff mismatch and target cutoff after deadline block.
- Full accepted FPL and Odds rights objects are checked. FPL derived storage remains effective
  DENY; the bridge reports no database, persistence, raw retention, cache, or backup operation.
- Resolution requests bind source semantics, the independently recomputed FPL identity view, Odds
  identity semantics, full Odds provenance, mapping-plan hashes/versions, and decision time. The
  final map embeds and revalidates both plans and all output hashes.
- Tests mutate nested identities, names, event context, rights, times, source/plan hashes, approval
  authority, mapping cardinality, orientation, kickoff, coverage, and final-map lineage.

## Material P2 checks

- No GW1 semantic label or `gameweek == 1` behavior remains; all positive fixtures use Gameweek 2.
- Common cutoff earlier than the official deadline passes, eliminating the donor equality residue.
- Provider events outside the target Gameweek are supported without imposing provider-count
  equality, while exact target collisions block as ambiguous.
- Odds prices and bookmaker/outcome ordering do not affect identity semantics. They do affect the
  separately bound provider acquisition/provenance lineage where the accepted source object does.
- No public summary or CLI was added. The private map's identifiers cannot cross an output surface
  introduced by this ticket.
- Historical/synthetic `OddsMappingPlan` and the accepted FPL/LIVE-ODDS input contracts are not
  weakened or replaced.

One P3 test-hygiene issue was found and closed before commit: a negative fuzzy-match test initially
reused a real-world abbreviation from the ticket's explanatory example, despite the synthetic-only
test-data rule. It now uses a synthetic club abbreviation. The same cleanup removed obsolete GW1
label literals from executable tests and changed an internally inconsistent target-Gameweek case
from 1 to 3, so the test cannot be misread as rejecting valid Gameweek 1 inputs. Product behavior
was unchanged.

The same-agent review finds no unresolved P0, P1, material in-scope P2, or P3. Independent review
remains required.
