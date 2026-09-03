"""PlanEvaluation domain models — deterministic, explainable, serialisable."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from trip_agent.evaluation.scoring import weighted_overall_score

type WarningCode = Literal[
    "TIGHT_TRANSFER",
    "HIGH_DAILY_LOAD",
    "BUDGET_NEAR_LIMIT",
    "LONG_WALKING",
    "LATE_DAY_END",
    "LOW_INTEREST_MATCH",
    "PROVIDER_FALLBACK_USED",
    "ESTIMATED_TRANSIT",
    "LOW_TIME_BUFFER",
]
type WarningSeverity = Literal["INFO", "WARNING", "CRITICAL"]
type EntityType = Literal["PLAN", "DAY", "ACTIVITY", "TRANSIT"]
type SubjectType = Literal["PLAN", "DAY", "ACTIVITY", "TRANSIT"]
type ReasonCode = Literal[
    "FIXED_APPOINTMENT",
    "NEARBY_CLUSTER",
    "MUST_VISIT",
    "TRANSIT_MODE",
    "SHORTEST_ROUTE",
    "PROVIDER_CONSTRAINT",
    "TIME_OPTIMIZATION",
    "BUDGET_CONSTRAINT",
    "REGIONAL_GROUPING",
    "PACE_POLICY",
    "INTEREST_MATCH",
    "EVIDENCE_STRENGTH",
]


class EvaluationDimensions(BaseModel):
    """Per-dimension scores (0–100)."""

    model_config = ConfigDict(
        frozen=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )

    constraint_satisfaction: int = Field(ge=0, le=100)
    time_feasibility: int = Field(ge=0, le=100)
    budget_fit: int | None = Field(default=None, ge=0, le=100)
    route_efficiency: int = Field(ge=0, le=100)
    interest_match: int | None = Field(default=None, ge=0, le=100)
    # M0 evidence dimension (rule-v6): how well-supported decisions are by
    # fused L1 evidence.  Optional so legacy schema-v1 plans (no evidence
    # field) keep validating; the current evaluator always emits it.
    evidence_strength: int | None = Field(default=None, ge=0, le=100)


class EvaluationWarning(BaseModel):
    """A structured, user-safe risk signal tied to a specific domain entity."""

    model_config = ConfigDict(
        frozen=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )

    code: WarningCode
    severity: WarningSeverity
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
    ]
    day_index: int | None = None
    entity_type: EntityType
    entity_id: UUID | None = None
    metric_key: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=60),
    ] = None
    actual_value: float | None = None
    threshold: float | None = None


class EvaluationEvidence(BaseModel):
    """A verifiable fact used to justify a decision or warning."""

    model_config = ConfigDict(
        frozen=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )

    key: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=60),
    ]
    label: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
    ]
    value: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]


class DecisionExplanation(BaseModel):
    """Why a particular plan, day, activity, or transit leg was chosen."""

    model_config = ConfigDict(
        frozen=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )

    subject_type: SubjectType
    subject_id: UUID | None = None
    summary: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
    ]
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1)
    reasons: tuple[
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
        ],
        ...,
    ] = Field(min_length=1)
    constraint_refs: tuple[UUID, ...] = ()
    evidence: tuple[EvaluationEvidence, ...] = ()
    day_index: int | None = None

    @field_validator("reasons")
    @classmethod
    def reasons_match_codes(cls, value: tuple[str, ...], info: object) -> tuple[str, ...]:
        codes = info.data.get("reason_codes", ()) if hasattr(info, "data") else ()
        if len(value) != len(codes):
            raise ValueError("each reasonCode must have a corresponding reason")
        return value


class PlanEvaluation(BaseModel):
    """Complete deterministic evaluation of a planning result."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_alias=True,
        validate_by_name=True,
        extra="forbid",
        frozen=True,
    )

    schema_version: Literal[1, 2] = 2
    evaluator_version: Annotated[
        str,
        StringConstraints(strip_whitespace=True, pattern=r"^rule-v\d+$"),
    ]
    feasible: Literal[True]
    overall_score: int = Field(ge=0, le=100)
    dimensions: EvaluationDimensions
    warnings: tuple[EvaluationWarning, ...] = ()
    decisions: tuple[DecisionExplanation, ...] = ()
    summary: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ]
    evaluated_at: datetime

    @model_validator(mode="after")
    def score_matches_dimensions(self) -> Self:
        dim = self.dimensions
        if self.schema_version == 1 and (
            dim.budget_fit is None or dim.interest_match is None
        ):
            raise ValueError("schemaVersion 1 requires all dimension scores")
        expected = weighted_overall_score(dim)
        if self.overall_score != expected:
            raise ValueError(
                f"overallScore ({self.overall_score}) "
                f"must equal weighted sum ({expected})"
            )
        return self

    @model_validator(mode="after")
    def feasible_only(self) -> Self:
        if not self.feasible:
            raise ValueError("PlanEvaluation.feasible must be true in completion")
        return self

    @field_validator("evaluated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("evaluatedAt must include a timezone")
        return value
