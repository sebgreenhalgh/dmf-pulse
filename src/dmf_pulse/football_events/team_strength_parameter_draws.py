"""Joint local penalised-curvature draws; public team evidence only, no I/O.

Binary64 matches the accepted fitting kernel. Decimal round-trip strings are
used at artifact boundaries. Fixed cohort centres and hyperparameters remain
conditional; this approximation is not an exact Bayesian posterior.
"""

from __future__ import annotations

import hashlib
import math
from decimal import Decimal, localcontext
from functools import lru_cache
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.football_events.team_strength_model import (
    Number,
    TeamStrengthModelArtifactV1,
    number,
    parameter_order,
)
from dmf_pulse.football_events.team_strength_numerics import cholesky, reconstruct
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SHA,
    FrozenEvidence,
    SealedEvidence,
    StrengthEvidenceError,
    authenticate,
    seal,
)

SYMMETRY_TOLERANCE = 1e-12
INVERSE_TOLERANCE = 1e-8
DRAW_REDERIVATION_ULPS = 8


class ParameterMixtureUnavailable(StrengthEvidenceError):
    """Explicit failure when requested research uncertainty cannot be constructed."""

    code = "PARAMETER_MIXTURE_UNAVAILABLE"


class ParameterDrawPolicyV1(SealedEvidence):
    schema_version: Literal["team-strength-draw-policy-v1"] = "team-strength-draw-policy-v1"
    parameter_uncertainty_method: Literal["LOCAL_LAPLACE_GAUSSIAN"] = "LOCAL_LAPLACE_GAUSSIAN"
    generator: Literal["SHA256_BOX_MULLER_CHOLESKY_V1"] = "SHA256_BOX_MULLER_CHOLESKY_V1"
    seed: int = Field(ge=0)
    draw_count: int = Field(gt=0)
    scale: Number = Field(ge=0)
    status: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"


def draw_policy(
    *, seed: int, draw_count: int, scale: Decimal = Decimal(1)
) -> ParameterDrawPolicyV1:
    return seal(ParameterDrawPolicyV1, seed=seed, draw_count=draw_count, scale=scale)


def unpack_triangle(values: tuple[Decimal, ...], dimension: int) -> tuple[tuple[float, ...], ...]:
    if dimension < 1 or len(values) != dimension * (dimension + 1) // 2:
        raise ParameterMixtureUnavailable("covariance dimension mismatch")
    result = tuple(
        tuple(float(values[max(i, j) * (max(i, j) + 1) // 2 + min(i, j)]) for j in range(dimension))
        for i in range(dimension)
    )
    if any(not math.isfinite(x) for row in result for x in row):
        raise ParameterMixtureUnavailable("nonfinite covariance")
    return result


def covariance_factor(matrix: tuple[tuple[float, ...], ...]) -> tuple[tuple[float, ...], ...]:
    """PSD factor, including exact zero covariance, without jitter or clipping.

    Tiny asymmetry <= 1e-12 * max(1, |Cij|, |Cji|) is averaged explicitly.
    Negative pivots always fail, even when small. Exact zero pivots require
    exact zero residual covariances; no uncertain coordinate is silently zeroed.
    """
    n = len(matrix)
    if n == 0 or any(len(row) != n for row in matrix):
        raise ParameterMixtureUnavailable("covariance shape mismatch")
    if any(not math.isfinite(x) for row in matrix for x in row):
        raise ParameterMixtureUnavailable("nonfinite covariance")
    if any(
        abs(matrix[i][j] - matrix[j][i])
        > SYMMETRY_TOLERANCE * max(1.0, abs(matrix[i][j]), abs(matrix[j][i]))
        for i in range(n)
        for j in range(i)
    ):
        raise ParameterMixtureUnavailable("materially asymmetric covariance")
    lower = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            value = (matrix[i][j] + matrix[j][i]) / 2 - math.fsum(
                lower[i][k] * lower[j][k] for k in range(j)
            )
            if not math.isfinite(value) or (i == j and value < 0):
                raise ParameterMixtureUnavailable("non-PSD covariance")
            if i == j:
                lower[i][j] = math.sqrt(value)
            elif lower[j][j] == 0:
                if value != 0:
                    raise ParameterMixtureUnavailable("singular covariance has nonzero residual")
            else:
                lower[i][j] = value / lower[j][j]
    return tuple(tuple(row) for row in lower)


def normal_vector(seed: int, index: int, dimension: int) -> tuple[float, ...]:
    """Counter-based normal pairs: count and fixture do not enter the RNG key."""
    result: list[float] = []
    for pair in range((dimension + 1) // 2):
        digest = hashlib.sha256(f"dmf-cts-u-v1:{seed}:{index}:{pair}".encode("ascii")).digest()
        # 52 bits plus half a unit ensure both uniforms are strictly inside (0,1).
        u = ((int.from_bytes(digest[:8], "big") >> 12) + 0.5) / (2**52)
        v = ((int.from_bytes(digest[8:16], "big") >> 12) + 0.5) / (2**52)
        radius = math.sqrt(-2 * math.log(u))
        result.extend((radius * math.cos(2 * math.pi * v), radius * math.sin(2 * math.pi * v)))
    return tuple(result[:dimension])


class ParameterDraw(FrozenEvidence):
    parameter_draw_id: SHA
    index: int = Field(ge=0)
    draw_weight: Number = Field(gt=0, le=1)
    free_parameters: tuple[Number, ...]


class ParameterDrawSetV1(SealedEvidence):
    schema_version: Literal["team-strength-joint-draws-v1"] = "team-strength-joint-draws-v1"
    structural_world_id: Literal[
        "REGULARISED_TIME_WEIGHTED_INDEPENDENT_POISSON_TEAM_STRENGTH_V1"
    ] = "REGULARISED_TIME_WEIGHTED_INDEPENDENT_POISSON_TEAM_STRENGTH_V1"
    parameter_uncertainty_method: Literal["LOCAL_LAPLACE_GAUSSIAN"] = "LOCAL_LAPLACE_GAUSSIAN"
    fit_artifact_sha256: SHA
    model_sha256: SHA
    covariance_sha256: SHA
    parameter_order_sha256: SHA
    teams: tuple[UUID, ...]
    parameter_order: tuple[str, ...]
    policy: ParameterDrawPolicyV1
    draw_policy_sha256: SHA
    draws: tuple[ParameterDraw, ...]
    status: Literal["SHADOW_NOT_MODEL_INPUT"] = "SHADOW_NOT_MODEL_INPUT"
    production_active: Literal[False] = False

    @model_validator(mode="after")
    def check_draws(self) -> Self:
        if self.teams != tuple(sorted(set(self.teams))) or len(self.teams) < 2:
            raise ValueError("noncanonical fitted universe")
        if self.parameter_order != parameter_order(self.teams):
            raise ValueError("parameter-order mismatch")
        if self.parameter_order_sha256 != canonical_sha256(self.parameter_order):
            raise ValueError("parameter-order hash mismatch")
        if self.draw_policy_sha256 != self.policy.semantic_sha256:
            raise ValueError("draw-policy identity mismatch")
        if len(self.draws) != self.policy.draw_count:
            raise ValueError("draw count mismatch")
        for i, row in enumerate(self.draws):
            if row.index != i or len(row.free_parameters) != len(self.parameter_order):
                raise ValueError("draw dimension/index mismatch")
            if row.parameter_draw_id != _draw_id(self.model_sha256, self.policy, i):
                raise ValueError("draw identity mismatch")
        with localcontext() as context:
            context.prec = 120
            if sum((row.draw_weight for row in self.draws), Decimal(0)) != 1:
                raise ValueError("draw weights do not sum to one")
        return self


def _draw_id(model_sha: str, policy: ParameterDrawPolicyV1, index: int) -> str:
    return canonical_sha256({"model": model_sha, "policy": policy.semantic_sha256, "index": index})


def joint_parameter_draws(
    artifact: TeamStrengthModelArtifactV1, *, policy: ParameterDrawPolicyV1
) -> ParameterDrawSetV1:
    artifact, policy = authenticate(artifact), authenticate(policy)
    model = artifact.model
    teams = tuple(row.team_id for row in model.effects)
    order = parameter_order(teams)
    if model.uncertainty.parameter_order != order:
        raise ParameterMixtureUnavailable("parameter-order mismatch")
    n, p = len(teams), len(order)
    beta = (
        float(model.mu),
        float(model.global_home_effect),
        *(float(row.attack) for row in model.effects[:-1]),
        *(float(row.defence) for row in model.effects[:-1]),
    )
    if any(not math.isfinite(value) for value in beta):
        raise ParameterMixtureUnavailable("nonfinite parameter vector")
    if any(
        abs(reconstruct(beta[start : start + n - 1])[-1] - float(getattr(model.effects[-1], name)))
        > 1e-12
        for start, name in ((2, "attack"), (n + 1, "defence"))
    ):
        raise ParameterMixtureUnavailable("invalid identifiability reconstruction")
    covariance = unpack_triangle(model.uncertainty.covariance, p)
    information = unpack_triangle(model.uncertainty.information, p)
    cholesky(information)
    lower = covariance_factor(covariance)
    if any(lower[i][i] <= 0 for i in range(p)):
        raise ParameterMixtureUnavailable("accepted fit covariance is not full rank")
    residual = max(
        abs(math.fsum(information[i][k] * covariance[k][j] for k in range(p)) - float(i == j))
        for i in range(p)
        for j in range(p)
    )
    if residual > INVERSE_TOLERANCE:
        raise ParameterMixtureUnavailable("covariance is not the accepted information inverse")
    rows = []
    with localcontext() as context:
        context.prec = 60
        weight = Decimal(1) / policy.draw_count
    with localcontext() as context:
        context.prec = 120
        last_weight = 1 - weight * (policy.draw_count - 1)
    for index in range(policy.draw_count):
        z = normal_vector(policy.seed, index, p)
        values = tuple(
            number(
                beta[i] + float(policy.scale) * math.fsum(lower[i][j] * z[j] for j in range(i + 1))
            )
            for i in range(p)
        )
        rows.append(
            ParameterDraw(
                parameter_draw_id=_draw_id(model.semantic_sha256, policy, index),
                index=index,
                draw_weight=weight if index < policy.draw_count - 1 else last_weight,
                free_parameters=values,
            )
        )
    return seal(
        ParameterDrawSetV1,
        fit_artifact_sha256=artifact.semantic_sha256,
        model_sha256=model.semantic_sha256,
        covariance_sha256=canonical_sha256(tuple(str(x) for x in model.uncertainty.covariance)),
        parameter_order_sha256=canonical_sha256(order),
        teams=teams,
        parameter_order=order,
        policy=policy,
        draw_policy_sha256=policy.semantic_sha256,
        draws=tuple(rows),
    )


class NestedDrawIdentity(FrozenEvidence):
    structural_world_id: str
    parameter_draw_id: SHA
    outcome_draw_id: str = Field(min_length=1)


@lru_cache(maxsize=4)
def _validated_draw_json(artifact_json: str, draws_json: str) -> ParameterDrawSetV1:
    artifact = TeamStrengthModelArtifactV1.model_validate_json(artifact_json)
    draws = ParameterDrawSetV1.model_validate_json(draws_json)
    expected = joint_parameter_draws(artifact, policy=draws.policy)
    # Persisted authoritative values retain their identity across binary64 libm
    # implementations. Only regenerated coordinates may differ by roundoff;
    # covariance, policies, IDs, weights and all other lineage remain exact.
    if draws.model_dump(exclude={"draws", "semantic_sha256"}) != expected.model_dump(
        exclude={"draws", "semantic_sha256"}
    ):
        raise ParameterMixtureUnavailable("draws differ from joint artifact-bound construction")
    for stored, regenerated in zip(draws.draws, expected.draws, strict=True):
        if stored.model_dump(exclude={"free_parameters"}) != regenerated.model_dump(
            exclude={"free_parameters"}
        ):
            raise ParameterMixtureUnavailable("draw identities/weights differ from construction")
        for actual, target in zip(stored.free_parameters, regenerated.free_parameters, strict=True):
            allowance = DRAW_REDERIVATION_ULPS * math.ulp(max(1.0, abs(float(target))))
            if abs(float(actual) - float(target)) > allowance:
                raise ParameterMixtureUnavailable(
                    "draw coordinates differ materially from construction"
                )
    return draws


def authenticate_parameter_draws(
    artifact: TeamStrengthModelArtifactV1, draws: ParameterDrawSetV1
) -> ParameterDrawSetV1:
    """Cache only full immutable bytes; a rehashed invented world is rejected."""
    return _validated_draw_json(artifact.model_dump_json(), draws.model_dump_json())


def outcome_identity(
    draws: ParameterDrawSetV1, *, parameter_index: int, outcome_draw_id: str
) -> NestedDrawIdentity:
    draws = authenticate(draws)
    if not 0 <= parameter_index < len(draws.draws):
        raise ParameterMixtureUnavailable("unknown parameter draw")
    return NestedDrawIdentity(
        structural_world_id=draws.structural_world_id,
        parameter_draw_id=draws.draws[parameter_index].parameter_draw_id,
        outcome_draw_id=outcome_draw_id,
    )
