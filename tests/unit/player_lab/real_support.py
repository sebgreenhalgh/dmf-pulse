"""Owned engineering fixtures only; none describe actual football or real rights."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.evaluation.artifacts import seal as stage_seal
from dmf_pulse.evaluation.benchmarks import benchmark_suite
from dmf_pulse.evaluation.models import DatasetMode, EvaluationLineage, ForecastArtifact
from dmf_pulse.fpl_points.models import POINT_COMPONENT_NAMES
from dmf_pulse.ingestion.models import (
    CapabilityValue,
    RightsCapability,
    RightsProfile,
    RightsProfileStatus,
)
from dmf_pulse.player_lab.contracts import FinalPlayerOutcome, PlayerKey, SourceRef, seal
from dmf_pulse.player_lab.real import (
    DeadlinePopulation,
    ModelBinding,
    RealPlayerProtocol,
    RealPointForecast,
)
from dmf_pulse.player_lab.real_rights import RealSourceQualification, RealSourceRegistry
from dmf_pulse.player_lab.rights import profile_identity

AT = datetime(2026, 10, 30, 12, tzinfo=UTC)


def reseal(value, **changes):
    values = {
        name: getattr(value, name) for name in type(value).model_fields if name != "semantic_sha256"
    }
    values.update(changes)
    return seal(type(value).model_construct(**values, semantic_sha256="0" * 64))


def owned_full(point):
    from dmf_pulse.player_lab.contracts import PlayerForecast

    components = {name: Decimal(0) for name in POINT_COMPONENT_NAMES}
    components[POINT_COMPONENT_NAMES[0]] = Decimal(4)
    return seal(
        PlayerForecast.model_construct(
            key=point.key,
            dataset_mode="PROSPECTIVE_REAL",
            model_id=point.model_id,
            model_version_ids=point.stage12.lineage.model_version_ids,
            training_cutoff=None,
            code_sha=point.stage12.lineage.code_commit,
            ruleset_sha256=point.stage12.lineage.ruleset_hash,
            source_summary_sha256="d" * 64,
            input_sha256=point.stage12.lineage.input_manifest_sha256,
            mean=Decimal(4),
            pmf={3: Decimal("0.5"), 5: Decimal("0.5")},
            components=components,
            expected_minutes=Decimal(60),
            position="MID",
            generated_at=point.generated_at,
            information_cutoff=point.information_cutoff,
            deadline_at=point.deadline_at,
            label_finality_cutoff=point.label_finality_cutoff,
            sources=point.sources,
            semantic_sha256="0" * 64,
        )
    )


def owned_case(now=AT, *, prospective=False):
    profile = RightsProfile(
        rights_profile_id="owned-engineering-only-player-fixture",
        provider_key="owned-engineering-only",
        profile_version="1.0.0",
        status=RightsProfileStatus.HUMAN_APPROVED,
        capabilities={key: CapabilityValue.ALLOW for key in RightsCapability},
        retention_seconds=None,
        retention_reason="Owned invented fixture, not an actual provider qualification",
        termination_deletion_required=False,
        attribution_required=False,
        geography_scope="OWNED_TEST",
        account_scope="OWNED_TEST",
        approved_purpose="PLAYER_FORECAST_RETENTION_AND_EVALUATION",
        terms_source="owned-engineering-fixture",
        terms_version="test-only",
        checked_at=now - timedelta(days=30),
        human_approval_id="OWNED_TEST_ONLY",
        approved_by="OWNED_TEST_ONLY",
        approved_at=now - timedelta(days=30),
    )
    source = SourceRef(
        source_id="owned-engineering-only-catalogue",
        payload_sha256="1" * 64,
        profile_id=profile.rights_profile_id,
        profile_sha256=profile_identity(profile),
        observed_at=now - timedelta(days=20),
        usable_at=now - timedelta(days=20),
    )
    label_source = source.model_copy(
        update={
            "source_id": "owned-engineering-only-labels",
            "payload_sha256": "2" * 64,
            "observed_at": now - timedelta(days=1),
            "usable_at": now - timedelta(days=1),
        }
    )
    weeks = (9, 10)
    deadlines = tuple(
        now + timedelta(minutes=5 + week) if prospective else now - timedelta(days=12 - week)
        for week in (0, 1)
    )
    populations, forecasts, labels = [], [], []
    for week, deadline in zip(weeks, deadlines, strict=True):
        keys = tuple(
            sorted(
                (
                    PlayerKey(
                        season="2026/27",
                        gameweek=week,
                        player_id=UUID(int=player),
                        fixture_ids=(UUID(int=week),),
                    )
                    for player in ((3, 4) if prospective else (1, 2))
                ),
                key=lambda key: key.target_id(),
            )
        )
        populations.append(
            DeadlinePopulation(
                gameweek=week,
                deadline_at=deadline,
                official_deadline_evidence_sha256="3" * 64,
                catalogue_source=source,
                targets=keys,
            )
        )
        for key in keys:
            issued = now + timedelta(seconds=1) if prospective else deadline - timedelta(hours=1)
            manifest = canonical_sha256([source.model_dump(mode="json")])
            lineage = EvaluationLineage(
                forecast_origin=issued,
                information_cutoff=source.usable_at,
                usable_at_cutoff=source.usable_at,
                training_cutoff=None,
                label_finality_cutoff=deadline + timedelta(days=15),
                model_version_ids=("owned-v1",),
                ruleset_id="OWNED_TEST_ONLY",
                ruleset_hash="4" * 64,
                code_commit="5" * 40,
                dataset_manifest_sha256=manifest,
                input_manifest_sha256="6" * 64,
            )
            stage = stage_seal(
                ForecastArtifact(
                    forecast_id="owned-" + key.target_id(),
                    benchmark_id="owned-point",
                    dataset_mode=DatasetMode.RAW_OBSERVED,
                    target_id=key.target_id(),
                    horizon=1,
                    point_forecast=Decimal("4"),
                    pmf={},
                    lineage=lineage,
                    issued_at=issued,
                    forecast_sha256="0" * 64,
                ),
                "forecast_sha256",
            )
            forecasts.append(
                seal(
                    RealPointForecast.model_construct(
                        key=key,
                        model_id="owned-point",
                        stage12=stage,
                        generated_at=issued,
                        information_cutoff=source.usable_at,
                        deadline_at=deadline,
                        label_finality_cutoff=deadline + timedelta(days=15),
                        sources=(source,),
                        semantic_sha256="0" * 64,
                    )
                )
            )
            components = {name: 0 for name in POINT_COMPONENT_NAMES}
            components[POINT_COMPONENT_NAMES[0]] = 2
            finalized = deadline + timedelta(days=1)
            if not prospective:
                labels.append(
                    seal(
                        FinalPlayerOutcome.model_construct(
                            key=key,
                            dataset_mode="PROSPECTIVE_REAL",
                            total_points=2,
                            components=components,
                            finalized_at=finalized,
                            original_points_lock_at=finalized,
                            finality_evidence_sha256="7" * 64,
                            retrieved_at=label_source.observed_at,
                            usable_at=label_source.usable_at,
                            source=label_source,
                            semantic_sha256="0" * 64,
                        )
                    )
                )
    protocol = seal(
        RealPlayerProtocol.model_construct(
            cohort_id="OWNED_ENGINEERING_ONLY",
            season="2026/27",
            registered_at=now - timedelta(minutes=1),
            gameweeks=weeks,
            evaluation_classification="PREREGISTERED_PROSPECTIVE"
            if prospective
            else "POST_ORIGIN_DESCRIPTIVE",
            first_deadline_at=deadlines[0],
            first_deadline_evidence_sha256="3" * 64,
            model_ids=("owned-point",),
            model_bindings=(
                ModelBinding(
                    model_id="owned-point",
                    code_sha="5" * 40,
                    model_version_ids=("owned-v1",),
                    ruleset_sha256="4" * 64,
                ),
            ),
            inner_gameweeks=(9,) if prospective else (),
            holdout_gameweeks=(10,) if prospective else weeks,
            sources=(source,),
            source_manifest_sha256=canonical_sha256([source.model_dump(mode="json")]),
            benchmark_definitions_sha256=canonical_sha256(
                [row.model_dump(mode="json") for row in benchmark_suite()]
            ),
            information_grade="RAW_OBSERVED",
            semantic_sha256="0" * 64,
        )
    )

    def qualification(ref, **extra):
        return RealSourceQualification(
            source=ref,
            profile=profile,
            purpose="PLAYER_FORECAST_RETENTION_AND_EVALUATION",
            source_classification="INDEPENDENTLY_QUALIFIED_REAL",
            decision_ref="OWNED_TEST_ONLY",
            independent_review_sha256="8" * 64,
            terms_evidence_sha256="9" * 64,
            qualified_at=ref.usable_at,
            valid_until=now + timedelta(days=30),
            **extra,
        )

    registry = RealSourceRegistry(
        sources=(
            qualification(
                source,
                qualified_population_sha256s=tuple(
                    canonical_sha256(row.model_dump(mode="json")) for row in populations
                ),
            ),
            qualification(
                label_source, qualified_label_sha256s=tuple(row.semantic_sha256 for row in labels)
            ),
        )
    )
    return protocol, tuple(populations), tuple(forecasts), tuple(labels), registry
