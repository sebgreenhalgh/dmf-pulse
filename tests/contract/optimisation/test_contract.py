from dmf_pulse.optimisation.models import OneGameweekOptimisationRequest


def test_request_does_not_expose_budget_or_raw_stage9_fields() -> None:
    assert "budget_tenths" not in OneGameweekOptimisationRequest.model_fields
    assert "stage9_points" not in OneGameweekOptimisationRequest.model_fields
