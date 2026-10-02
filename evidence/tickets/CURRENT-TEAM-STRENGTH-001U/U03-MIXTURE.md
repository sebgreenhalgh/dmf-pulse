# U.03 mixture construction

Schema: team-strength-parameter-mixture-fixture-v1. Conditional draws reuse the
same joint draw set across fixtures. Each component uses the accepted six-place
rate boundary and independent-Poisson kernel; no rate is clipped. The common
adaptive support is selected from the maximum drawn rates under the unchanged
Stage-8 tail policy. Conditional retained grids are normalized individually,
then weighted. Internal research matrices retain Decimal precision 60; Stage-8
public matrices use the existing exact 12-place simplex boundary. The omitted
mass and expectation discrepancy remain explicit. Total predictive variance
is E(lambda) + Var(lambda), not parameter variance alone.

Zero-scale gives the exact plug-in grid with separate mixture identity. There
is no requested-mixture fallback to a plug-in when sampling is unavailable.

Verification: 4 mixture tests passed; 16 parameter tests passed; strict mypy,
Ruff formatting and lint passed for the new modules. No new dependency.
