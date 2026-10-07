"""Схемы и связи: что рубрика и оценки держат форму и ссылаются на существующее."""

import pytest

from assess.content import ContentError, load_assessments


def test_rubric_loads_with_weights_and_blocking(rubric):
    assert len(rubric.dimensions) == 12
    assert rubric.weight_total == pytest.approx(28)
    blocking = {item["id"] for item in rubric.dimensions if item.get("blocking")}
    assert blocking == {"data-knowledge", "security", "evaluation"}


def test_every_dimension_belongs_to_a_group(rubric):
    groups = {item["id"] for item in rubric.groups}
    assert all(item["group"] in groups for item in rubric.dimensions)


def test_criteria_ids_are_unique_across_the_rubric(rubric):
    ids = [item["id"] for dimension in rubric.dimensions for item in dimension["criteria"]]
    assert len(ids) == len(set(ids))


def test_examples_load(examples):
    assert {item.id for item in examples} == {"demo-retail-support", "demo-logistics-intake"}


def test_final_assessment_covers_every_dimension(retail, rubric):
    assert set(retail.scores) == {item["id"] for item in rubric.dimensions}


def test_evidence_points_at_a_declared_source(examples):
    for assessment in examples:
        known = {source["id"] for source in assessment.sources}
        for dimension, score in assessment.scores.items():
            assert set(score.get("evidence", [])) <= known, dimension


def test_unknown_dimension_is_rejected(write_assessment, rubric):
    def mutate(data):
        data["scores"]["нет-такого"] = data["scores"]["security"]

    with pytest.raises(ContentError) as error:
        load_assessments(write_assessment(mutate), rubric)
    assert any("нет такого измерения" in problem for problem in error.value.problems)


def test_criterion_from_another_dimension_is_rejected(write_assessment, rubric):
    def mutate(data):
        data["scores"]["security"]["criteria"]["ev-dataset"] = 2

    with pytest.raises(ContentError) as error:
        load_assessments(write_assessment(mutate), rubric)
    assert any("не принадлежит этому измерению" in problem for problem in error.value.problems)


def test_final_requires_recommendation_for_a_weak_dimension(write_assessment, rubric):
    def mutate(data):
        del data["scores"]["security"]["recommendation"]

    with pytest.raises(ContentError) as error:
        load_assessments(write_assessment(mutate), rubric)
    assert any("без рекомендации" in problem for problem in error.value.problems)


def test_draft_may_leave_dimensions_unscored(write_assessment, rubric):
    def mutate(data):
        data["status"] = "draft"
        for dimension in ("security", "evaluation", "governance"):
            del data["scores"][dimension]

    loaded = load_assessments(write_assessment(mutate), rubric)
    assert len(loaded) == 1
    assert "security" not in loaded[0].scores


def test_id_must_match_the_file_name(write_assessment, rubric):
    def mutate(data):
        data["id"] = "demo-retail-support"
        data["project"]["name"] = "Переименованный проект"

    where = write_assessment(mutate)
    (where / "demo-retail-support.yaml").rename(where / "another-name.yaml")
    with pytest.raises(ContentError) as error:
        load_assessments(where, rubric)
    assert any("не совпадает с именем файла" in problem for problem in error.value.problems)


def test_empty_directory_is_an_error(tmp_path, rubric):
    with pytest.raises(ContentError):
        load_assessments(tmp_path, rubric)
