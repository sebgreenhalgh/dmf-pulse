"""The diagnostic decision cannot reset standing spend or grant live authority."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from dmf_pulse.operation.campaign import (
    DiagnosticBudgetPreview,
    DiagnosticCampaignProposal,
    DiagnosticLimits,
    DiagnosticPaidGateProof,
    DiagnosticSessionSummary,
    preview_diagnostic_budget,
    preview_diagnostic_paid_reservation,
)
from dmf_pulse.operation.models import OperationError

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)
DEADLINE = datetime(2026, 11, 6, 18, 30, tzinfo=UTC)


def proposal() -> DiagnosticCampaignProposal:
    fields = {
        name: "a" * 64
        for name in (
            "owner_request_sha256",
            "original_ledger_id",
            "original_consumed_execution_key",
            "original_standing_material_sha256",
            "original_standing_policy_sha256",
            "original_owner_acceptance_sha256",
            "original_root_trust_sha256",
            "review_public_key_sha256",
            "protected_numerical_sha256",
            "original_marker_manifest_sha256",
            "fpl_permission_sha256",
            "odds_permission_sha256",
            "source_scope_sha256",
            "official_deadline_observation_sha256",
        )
    }
    return DiagnosticCampaignProposal.model_validate(
        {
            **fields,
            "owner_ref": "owned-test-operator",
            "entry_id": 123,
            "odds_account_ref": "owned-test-odds-account",
            "plan_ref": "owned-test-plan",
            "plan_credit_allowance": 500,
            "created_at": NOW - timedelta(hours=1),
            "deadline_not_after": DEADLINE,
        }
    )


def session(index: int, *, paid: bool = False, **changes: object) -> DiagnosticSessionSummary:
    return DiagnosticSessionSummary.model_validate(
        {
            "campaign_sha256": proposal().semantic_sha256,
            "session_index": index,
            "mode": "PAID_ELIGIBLE" if paid else "READ_ONLY",
            "started_at": NOW - timedelta(minutes=1),
            "terminal": True,
            "inspected": True,
            "successful_real_recommendation": False,
            "unresolved_paid_consumption": False,
            "terminal_diagnostics_sha256": "b" * 64,
            **changes,
        }
    )


def preview(
    rows: tuple[DiagnosticSessionSummary, ...] = (), **changes: object
) -> DiagnosticBudgetPreview:
    return preview_diagnostic_budget(  # type: ignore[arg-type]
        proposal(),
        rows,
        **{
            "mode": "READ_ONLY",
            "now": NOW,
            "fresh_official_gameweek": 10,
            "fresh_official_deadline": DEADLINE,
            **changes,
        },
    )


def test_read_only_preview_has_no_monetary_or_runtime_authority() -> None:
    result = preview()
    assert result.reserved_credits == 0 and result.runtime_authority is False
    assert result.state == "BUDGET_PREVIEW_NOT_AUTHORIZATION"
    assert proposal().state == "PROPOSED_NO_RUNTIME_AUTHORITY"


def test_paid_eligible_starts_without_financial_reservation() -> None:
    result = preview(mode="PAID_ELIGIBLE")
    assert result.reserved_credits == 0
    assert result.remaining_paid_eligible_sessions_after_admission == 3


def test_eighth_session_allowed_and_ninth_refused() -> None:
    assert preview(tuple(session(i) for i in range(1, 8))).session_index == 8
    with pytest.raises(OperationError, match="SESSION_LIMIT_EXHAUSTED"):
        preview(tuple(session(i) for i in range(1, 9)))


def test_four_paid_slots_consume_limit_even_with_zero_actual_charge() -> None:
    rows = tuple(session(i, paid=True) for i in range(1, 5))
    with pytest.raises(OperationError, match="PAID_SLOT_LIMIT_EXHAUSTED"):
        preview(rows, mode="PAID_ELIGIBLE")
    assert preview(rows).reserved_credits == 0


@pytest.mark.parametrize("changes", [{"terminal": False, "inspected": False}, {"inspected": False}])
def test_prior_inspection_required(changes: dict[str, bool]) -> None:
    with pytest.raises(OperationError, match="INSPECTION_REQUIRED"):
        preview((session(1, **changes),))


def test_all_prior_sessions_must_be_inspected() -> None:
    with pytest.raises(OperationError, match="INSPECTION_REQUIRED"):
        preview((session(1, inspected=False), session(2)))


def test_unknown_paid_cost_blocks_paid_session_but_permits_readonly_reconciliation() -> None:
    with pytest.raises(OperationError, match="PAID_CONSUMPTION_UNRESOLVED"):
        preview(
            (session(1, paid=True, paid_credits_reserved=True, unresolved_paid_consumption=True),),
            mode="PAID_ELIGIBLE",
        )
    assert (
        preview(
            (session(1, paid=True, paid_credits_reserved=True, unresolved_paid_consumption=True),)
        ).reserved_credits
        == 0
    )


def test_success_stops_diagnostic_campaign() -> None:
    with pytest.raises(OperationError, match="CAMPAIGN_ALREADY_SUCCEEDED"):
        preview(
            (
                session(
                    1,
                    paid=True,
                    paid_credits_reserved=True,
                    successful_real_recommendation=True,
                    real_publication_sha256="d" * 64,
                ),
            )
        )


@pytest.mark.parametrize(
    "rows", [(session(2),), (session(1), session(1)), (session(1, campaign_sha256="c" * 64),)]
)
def test_history_cannot_skip_duplicate_or_change_campaign(
    rows: tuple[DiagnosticSessionSummary, ...],
) -> None:
    with pytest.raises(OperationError, match="SESSION_HISTORY_INVALID"):
        preview(rows)


@pytest.mark.parametrize("gameweek", [9, 11, True, 10.0])
def test_only_exact_official_gw10(gameweek: object) -> None:
    with pytest.raises(OperationError, match="OFFICIAL_GAMEWEEK_MISMATCH"):
        preview(fresh_official_gameweek=gameweek)


@pytest.mark.parametrize(
    "now", [DEADLINE, DEADLINE + timedelta(seconds=1), NOW - timedelta(days=1)]
)
def test_deadline_and_clock_regression_fail_closed(now: datetime) -> None:
    with pytest.raises(OperationError, match="WINDOW_EXPIRED_OR_REGRESSED"):
        preview(now=now)


def test_earlier_fresh_deadline_cannot_be_overruled_by_pinned_deadline() -> None:
    with pytest.raises(OperationError, match="WINDOW_EXPIRED_OR_REGRESSED"):
        preview(fresh_official_deadline=NOW)


def test_naive_clock_is_rejected() -> None:
    with pytest.raises(ValidationError):
        preview(now=NOW.replace(tzinfo=None))


@pytest.mark.parametrize("bad", [True, 8.0, "8", 9])
def test_session_cap_cannot_be_coerced_or_expanded(bad: object) -> None:
    with pytest.raises(ValidationError):
        DiagnosticLimits(maximum_sessions=bad)  # type: ignore[arg-type]


def test_stable_session_key_ignores_administrative_proposal_timestamp() -> None:
    one = preview()
    changed = proposal().model_copy(update={"created_at": NOW - timedelta(minutes=30)})
    two = preview_diagnostic_budget(
        changed,
        (),
        mode="READ_ONLY",
        now=NOW,
        fresh_official_gameweek=10,
        fresh_official_deadline=DEADLINE,
    )
    assert one.session_key == two.session_key


def test_inspection_requires_retained_terminal_receipt() -> None:
    with pytest.raises(ValidationError):
        session(1, terminal_diagnostics_sha256=None)


def test_original_standing_policy_and_fpl_writes_cannot_be_enabled() -> None:
    for key in ("standing_material_policy_changed", "fpl_writes"):
        with pytest.raises(ValidationError):
            DiagnosticCampaignProposal.model_validate({**proposal().model_dump(), key: True})


def proof(**changes: object) -> DiagnosticPaidGateProof:
    return DiagnosticPaidGateProof.model_validate(
        {
            "campaign_sha256": proposal().semantic_sha256,
            "session_index": 1,
            "fpl_validation_sha256": "b" * 64,
            "controlled_pipeline_sha256": "c" * 64,
            "controlled_classification": "REAL_FPL_CONTROLLED_MARKET_ENGINEERING",
            "actual_fpl_contracts_passed": True,
            "stage8_stage9_stage12_passed": True,
            "fpl_validation_completed_at": NOW - timedelta(seconds=3),
            "controlled_pipeline_completed_at": NOW - timedelta(seconds=2),
            "quota_received_at": NOW - timedelta(seconds=1),
            "quota_remaining_credits": 500,
            "quota_used_credits": 0,
            "quota_reconciled_with_original_account": True,
            "credential_expires_at": NOW + timedelta(hours=1),
            "official_gameweek": 10,
            "official_deadline_at": DEADLINE,
            **changes,
        }
    )


def active_session(**changes: object) -> DiagnosticSessionSummary:
    return session(1, paid=True, terminal=False, inspected=False, **changes)


def test_paid_subgrant_uses_actual_later_time_without_backdating() -> None:
    value = preview_diagnostic_paid_reservation(proposal(), (active_session(),), proof(), now=NOW)
    assert value.issued_at == NOW and value.reserved_credits == 2
    assert value.expires_at == NOW + timedelta(seconds=900)
    assert value.acquisition_ends_at == NOW + timedelta(seconds=300)
    assert value.runtime_authority is False
    assert value.state == "PAID_RESERVATION_PREVIEW_NOT_AUTHORIZATION"


@pytest.mark.parametrize(
    "changes",
    [
        {"paid_credits_reserved": True},
        {"paid_credits_reserved": True, "unresolved_paid_consumption": True},
    ],
)
def test_paid_subgrant_cannot_repeat_or_ignore_unknown_spend(changes: dict[str, bool]) -> None:
    with pytest.raises(OperationError):
        preview_diagnostic_paid_reservation(
            proposal(), (active_session(**changes),), proof(), now=NOW
        )


def test_readonly_session_cannot_become_paid() -> None:
    with pytest.raises(OperationError, match="PAID_SESSION_NOT_ACTIVE"):
        preview_diagnostic_paid_reservation(
            proposal(), (session(1, terminal=False, inspected=False),), proof(), now=NOW
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"actual_fpl_contracts_passed": False},
        {"stage8_stage9_stage12_passed": False},
        {"quota_reconciled_with_original_account": False},
        {"controlled_classification": "REAL_PRIVATE"},
    ],
)
def test_every_controlled_gate_is_explicit_and_not_real_publication(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        proof(**changes)


@pytest.mark.parametrize("changes", [{"campaign_sha256": "d" * 64}, {"session_index": 2}])
def test_paid_gate_cannot_be_reused_for_another_session(changes: dict[str, object]) -> None:
    with pytest.raises(OperationError, match="PAID_GATE_BINDING_INVALID"):
        preview_diagnostic_paid_reservation(
            proposal(), (active_session(),), proof(**changes), now=NOW
        )


@pytest.mark.parametrize("at", [NOW - timedelta(seconds=301), NOW + timedelta(seconds=1)])
def test_paid_gate_requires_fresh_nonfuture_quota(at: datetime) -> None:
    with pytest.raises(OperationError, match="PAID_QUOTA_STALE"):
        preview_diagnostic_paid_reservation(
            proposal(), (active_session(),), proof(quota_received_at=at), now=NOW
        )


def test_paid_gate_preserves_ten_credit_safety_buffer() -> None:
    with pytest.raises(OperationError, match="SAFETY_RESERVE_REQUIRED"):
        preview_diagnostic_paid_reservation(
            proposal(),
            (active_session(),),
            proof(quota_remaining_credits=11, quota_used_credits=489),
            now=NOW,
        )


@pytest.mark.parametrize("remaining,used", [(500, 500), (501, 0), (12, 0)])
def test_reconciled_flag_cannot_override_contradictory_account_counters(
    remaining: int, used: int
) -> None:
    with pytest.raises(OperationError, match="QUOTA_CONTRADICTS_PLAN"):
        preview_diagnostic_paid_reservation(
            proposal(),
            (active_session(),),
            proof(quota_remaining_credits=remaining, quota_used_credits=used),
            now=NOW,
        )


def test_readonly_cannot_claim_real_publication() -> None:
    with pytest.raises(ValidationError):
        session(1, successful_real_recommendation=True, real_publication_sha256="d" * 64)


def test_real_publication_cannot_have_unresolved_paid_consumption() -> None:
    with pytest.raises(ValidationError):
        session(
            1,
            paid=True,
            paid_credits_reserved=True,
            unresolved_paid_consumption=True,
            successful_real_recommendation=True,
            real_publication_sha256="d" * 64,
        )


def test_unknown_paid_consumption_requires_a_real_reservation() -> None:
    with pytest.raises(ValidationError):
        session(1, paid=True, unresolved_paid_consumption=True)


@pytest.mark.parametrize(
    "age,code", [(1800, "SESSION_WINDOW_EXPIRED"), (1200, "PRE_PAID_WINDOW_EXPIRED")]
)
def test_paid_gate_enforces_session_and_prepaid_time_ceiling(age: int, code: str) -> None:
    with pytest.raises(OperationError, match=code):
        preview_diagnostic_paid_reservation(
            proposal(), (active_session(started_at=NOW - timedelta(seconds=age)),), proof(), now=NOW
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"fpl_validation_completed_at": NOW + timedelta(seconds=1)},
        {"controlled_pipeline_completed_at": NOW},
    ],
)
def test_paid_gate_cannot_rewrite_prior_phase_chronology(changes: dict[str, object]) -> None:
    with pytest.raises(OperationError, match="GATE_CHRONOLOGY_INVALID"):
        preview_diagnostic_paid_reservation(
            proposal(), (active_session(),), proof(**changes), now=NOW
        )


def test_paid_subgrant_cannot_extend_beyond_original_session_end() -> None:
    value = preview_diagnostic_paid_reservation(
        proposal(), (active_session(started_at=NOW - timedelta(seconds=1199)),), proof(), now=NOW
    )
    assert value.expires_at == NOW + timedelta(seconds=601)


def test_paid_subgrant_also_clamps_to_actual_credential_and_acquisition_end() -> None:
    value = preview_diagnostic_paid_reservation(
        proposal(),
        (active_session(),),
        proof(credential_expires_at=NOW + timedelta(seconds=80)),
        now=NOW,
    )
    assert value.expires_at == value.acquisition_ends_at == NOW + timedelta(seconds=80)


def test_expired_credential_never_admits_paid_subgrant() -> None:
    with pytest.raises(OperationError, match="CREDENTIAL_OR_WINDOW_EXPIRED"):
        preview_diagnostic_paid_reservation(
            proposal(), (active_session(),), proof(credential_expires_at=NOW), now=NOW
        )
