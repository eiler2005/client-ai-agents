import copy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from assess.content import (  # noqa: E402
    Assessment,
    load_assessments,
    load_company,
    load_proposals,
    load_rubric,
)
from assess.scoring import score  # noqa: E402

EXAMPLES = ROOT / "examples"
EXAMPLE_ASSESSMENTS = EXAMPLES / "assessments"
EXAMPLE_PROPOSALS = EXAMPLES / "proposals"


@pytest.fixture(scope="session")
def rubric():
    return load_rubric()


@pytest.fixture(scope="session")
def company():
    return load_company()


@pytest.fixture(scope="session")
def examples(rubric):
    return load_assessments(EXAMPLE_ASSESSMENTS, rubric)


@pytest.fixture(scope="session")
def proposals(company):
    return load_proposals(EXAMPLE_PROPOSALS, company)


@pytest.fixture(scope="session")
def offer(proposals):
    return next(item for item in proposals if item.id == "demo-retail-support-kp")


@pytest.fixture(scope="session")
def retail(examples):
    return next(item for item in examples if item.id == "demo-retail-support")


@pytest.fixture
def result(retail, rubric):
    return score(retail, rubric)


@pytest.fixture
def make_assessment(retail):
    """Копия показательной оценки, которую тест может испортить как захочет."""

    def build(**changes) -> Assessment:
        data = copy.deepcopy(retail.data)
        data.update(changes)
        return Assessment(data, retail.path)

    return build


@pytest.fixture
def write_assessment(tmp_path, retail):
    """Пишет изменённую копию оценки в отдельный каталог и возвращает его."""

    def build(mutate) -> Path:
        data = copy.deepcopy(retail.data)
        mutate(data)
        target = tmp_path / f"{data['id']}.yaml"
        target.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return tmp_path

    return build


@pytest.fixture
def write_proposal(tmp_path, offer):
    """То же для предложения: изменённая копия в своём каталоге."""

    def build(mutate) -> Path:
        data = copy.deepcopy(offer.data)
        mutate(data)
        target = tmp_path / f"{data['id']}.yaml"
        target.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return tmp_path

    return build
