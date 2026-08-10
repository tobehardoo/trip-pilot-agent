"""B2 RED 1 — rule catalog: stable, ordered, unique rule IDs.

The catalog is the single source of truth for which hard rules exist
(REQUIRED_RULE_IDS) and which the current validator actually executes
(IMPLEMENTED_RULE_IDS).  Order and membership are contract-level facts
and must be locked by tests.
"""


from trip_agent.feasibility.catalog import (
    IMPLEMENTED_RULE_IDS,
    MISSING_RULE_IDS,
    REQUIRED_RULE_IDS,
    RuleId,
)


def test_required_rule_ids_are_the_exact_eleven_in_stable_order() -> None:
    assert REQUIRED_RULE_IDS == (
        "TRIP_DATE_RANGE",
        "FIXED_SCHEDULE_COVERAGE",
        "BUDGET_LIMIT",
        "MUST_VISIT_COVERAGE",
        "DUPLICATE_POI",
        "ACTIVITY_OVERLAP",
        "ROUTE_ENDPOINT_CONTINUITY",
        "CROSS_DAY_CONTINUITY",
        "OPENING_HOURS",
        "VISIT_DURATION",
        "MEAL_WINDOW",
    )


def test_required_rule_ids_are_unique_and_non_empty() -> None:
    assert len(REQUIRED_RULE_IDS) == 11
    assert len(set(REQUIRED_RULE_IDS)) == 11
    assert all(isinstance(rule_id, str) and rule_id for rule_id in REQUIRED_RULE_IDS)


def test_implemented_rule_ids_are_a_stable_seven_subset_of_required() -> None:
    assert IMPLEMENTED_RULE_IDS == (
        "TRIP_DATE_RANGE",
        "FIXED_SCHEDULE_COVERAGE",
        "BUDGET_LIMIT",
        "DUPLICATE_POI",
        "ACTIVITY_OVERLAP",
        "ROUTE_ENDPOINT_CONTINUITY",
        "CROSS_DAY_CONTINUITY",
    )
    assert set(IMPLEMENTED_RULE_IDS).issubset(set(REQUIRED_RULE_IDS))
    assert len(set(IMPLEMENTED_RULE_IDS)) == len(IMPLEMENTED_RULE_IDS) == 7


def test_missing_rule_ids_are_exactly_the_four_future_rules() -> None:
    assert MISSING_RULE_IDS == (
        "MUST_VISIT_COVERAGE",
        "OPENING_HOURS",
        "VISIT_DURATION",
        "MEAL_WINDOW",
    )
    assert set(MISSING_RULE_IDS) == set(REQUIRED_RULE_IDS) - set(IMPLEMENTED_RULE_IDS)


def test_rule_id_enum_members_are_non_empty_and_unique() -> None:
    members = list(RuleId)
    assert len(members) == 11
    assert len({member.value for member in members}) == 11
    assert all(member.value for member in members)
    # Every required id must map to an enum member and vice versa.
    assert {member.value for member in members} == set(REQUIRED_RULE_IDS)


def test_rule_ids_are_not_generated_from_sets() -> None:
    # Order must be definitional, not hash-dependent.  A set-derived order
    # would be unstable across runs; the tuple above is the contract.
    assert isinstance(REQUIRED_RULE_IDS, tuple)
    assert isinstance(IMPLEMENTED_RULE_IDS, tuple)
    assert isinstance(MISSING_RULE_IDS, tuple)


def test_openings_hours_rule_id_is_the_b1_contract_identifier() -> None:
    # B1 locked the rule id "OPENING_HOURS" as the evidence-rule identifier.
    assert RuleId.OPENING_HOURS.value == "OPENING_HOURS"
    assert "OPENING_HOURS" in REQUIRED_RULE_IDS
