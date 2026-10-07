"""Арифметика оценки, блокирующие измерения и пороги решения."""

import pytest

from assess.scoring import action_priority, percent_of, portfolio, risk_weight, score


def test_percent_is_level_over_max(rubric):
    assert percent_of(0, rubric.max_level) == 0
    assert percent_of(2, rubric.max_level) == 50
    assert percent_of(4, rubric.max_level) == 100


def test_overall_is_the_weighted_mean_of_scored_dimensions(result, rubric):
    expected = sum(
        item.weight * percent_of(item.level, rubric.max_level) for item in result.scored
    ) / sum(item.weight for item in result.scored)
    assert result.overall == pytest.approx(expected)


def test_unscored_dimension_lowers_coverage_and_not_the_score(make_assessment, rubric):
    full = score(make_assessment(), rubric)
    partial_data = make_assessment()
    # Убираем сильное измерение: балл по оставшимся не должен получить ноль за него.
    del partial_data.scores["architecture"]
    partial = score(partial_data, rubric)
    assert partial.coverage < full.coverage
    assert partial.overall > 0
    assert all(item.scored for item in partial.scored)


def test_blocking_dimension_caps_the_verdict(make_assessment, rubric):
    data = make_assessment()
    for dimension in data.scores.values():
        dimension["level"] = 4
    data.scores["security"]["level"] = 1
    result = score(data, rubric)
    assert result.overall > rubric.verdict("go")["min_score"]
    assert result.verdict["id"] == "fix"
    assert [item.id for item in result.blockers] == ["security"]


def test_blocking_dimension_at_level_two_does_not_cap(make_assessment, rubric):
    data = make_assessment()
    for dimension in data.scores.values():
        dimension["level"] = 4
    data.scores["security"]["level"] = 2
    result = score(data, rubric)
    assert result.blockers == []
    assert result.verdict["id"] == "go"


def test_manual_decision_wins_but_is_reported(make_assessment, rubric):
    data = make_assessment()
    data.verdict_note = {"decision": "go"}
    result = score(data, rubric)
    assert result.verdict["id"] == "go"
    assert result.computed_verdict["id"] != "go"
    assert result.overridden
    assert any("вместо расчётного" in note for note in result.notes)


def test_criteria_far_from_the_level_produce_a_note(make_assessment, rubric):
    data = make_assessment()
    data.scores["architecture"]["criteria"] = {"ar-boundaries": 0, "ar-tools": 0, "ar-state": 0}
    result = score(data, rubric)
    assert any("расходится со средним" in note for note in result.notes)


def test_high_level_on_low_confidence_produces_a_note(make_assessment, rubric):
    data = make_assessment()
    data.scores["architecture"]["confidence"] = "low"
    result = score(data, rubric)
    assert any("низкой уверенности" in note for note in result.notes)


def test_clean_assessment_has_no_notes(result):
    assert result.notes == []


def test_gaps_are_ordered_by_what_the_score_loses(result):
    gaps = result.gaps
    assert gaps
    assert [item.gap for item in gaps] == sorted((item.gap for item in gaps), reverse=True)
    assert all(item.level <= 2 for item in gaps)


def test_critical_risks_need_both_probability_and_impact(result):
    for risk in result.critical_risks:
        assert risk_weight(risk) >= 3


def test_action_priority_prefers_more_impact_for_less_effort():
    cheap = {"title": "a", "impact": "high", "effort": "s"}
    costly = {"title": "b", "impact": "high", "effort": "l"}
    assert action_priority(cheap) < action_priority(costly)


def test_plan_covers_every_horizon(result):
    horizons = [horizon for horizon, _ in result.plan()]
    assert horizons == [30, 60, 90]


def test_portfolio_sorts_by_readiness(examples, rubric):
    rows = portfolio([score(item, rubric) for item in examples])
    assert [row["overall"] for row in rows] == sorted(
        (row["overall"] for row in rows), reverse=True
    )
    assert all("verdict" in row for row in rows)
