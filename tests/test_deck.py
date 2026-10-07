"""Рукописная презентация сохраняет данные, источники и ограничения формата."""

import copy
import hashlib

import pytest
import yaml

from assess import deck
from assess.cli import main
from assess.content import ContentError


@pytest.fixture
def write_deck(tmp_path):
    data = {
        "id": "demo-meeting",
        "kind": "concept",
        "date": "2026-10-06",
        "client": "Вымышленная компания",
        "status": "draft",
        "slides": [
            {
                "kind": "cover",
                "title": "Консультация по каталогу оборудования",
                "subtitle": "Материалы для обсуждения",
            },
            {
                "kind": "closing",
                "title": "Следующий шаг — проверить источники",
                "points": ["Обсудить формат каталога"],
            },
        ],
    }

    def write(mutate=lambda item: None):
        current = copy.deepcopy(data)
        mutate(current)
        path = tmp_path / "deck.yaml"
        path.write_text(yaml.safe_dump(current, allow_unicode=True), encoding="utf-8")
        return path

    return write


def test_authored_deck_keeps_profile_contacts_sources_and_input_hashes(write_deck, company):
    chosen = company.contacts_for()[0]["id"]
    path = write_deck(lambda data: data.update(contacts=[chosen]))
    loaded = deck.load(path, company)
    assert loaded["slides"][0]["status"] == "draft"
    assert loaded["slides"][-1]["contacts"] == company.contacts_for([chosen])
    assert loaded["references"] == list(company.sources.values())
    assert any("Черновик" in warning for warning in loaded["warnings"])
    hashes = {item["name"]: item["sha256"] for item in loaded["inputs"]}
    assert hashes[path.name] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert {"company.yaml", "deck.schema.json", "deck.py", "presentation.mjs"} <= hashes.keys()


def test_table_continuations_preserve_every_row_and_source(write_deck, company):
    rows = [[f"Условие {index}", f"Результат {index}"] for index in range(5)]

    def with_table(data):
        data["slides"].insert(
            1,
            {
                "kind": "table",
                "title": "Условия определяют результат проверки",
                "headers": ["Условие", "Результат"],
                "rows": rows,
                "source": "Утверждённый пример",
            },
        )

    loaded = deck.load(write_deck(with_table), company)
    tables = [part for part in loaded["slides"] if part["kind"] == "table"]
    assert [row for part in tables for row in part["rows"]] == rows
    assert [part["page"] for part in tables] == [1, 2, 3]
    assert all(part["pages"] == 3 and part["source"] == "Утверждённый пример" for part in tables)


def test_unknown_contact_is_rejected(write_deck, company):
    with pytest.raises(ContentError) as error:
        deck.load(write_deck(lambda data: data.update(contacts=["missing-contact"])), company)
    assert any("неизвестный контакт" in problem for problem in error.value.problems)


def test_table_with_mismatched_columns_is_rejected(write_deck, company):
    def bad_table(data):
        data["slides"].append(
            {
                "kind": "table",
                "title": "Условия определяют результат проверки",
                "headers": ["Условие", "Владелец", "Результат"],
                "rows": [["Условие", "Результат"]],
            }
        )

    with pytest.raises(ContentError) as error:
        deck.load(write_deck(bad_table), company)
    assert any("не совпадает с шапкой" in problem for problem in error.value.problems)


def test_final_requires_a_closing_slide(write_deck, company):
    def missing_closing(data):
        data["status"] = "final"
        data["slides"][-1]["kind"] = "points"

    with pytest.raises(ContentError) as error:
        deck.load(write_deck(missing_closing), company)
    assert any("заканчивается слайдом closing" in problem for problem in error.value.problems)


def test_deck_command_reports_content_error_without_building(write_deck, monkeypatch, capsys):
    def unexpected_build(*args):
        pytest.fail("Ошибка содержимого должна остановить сборку")

    monkeypatch.setattr("assess.cli.slides.build", unexpected_build)
    path = write_deck(lambda data: data.update(contacts=["missing-contact"]))
    assert main(["deck", "--spec", str(path)]) == 1
    assert "неизвестный контакт" in capsys.readouterr().err
