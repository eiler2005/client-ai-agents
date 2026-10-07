"""Профиль компании и коммерческое предложение: связность, источники, сборка."""

import pytest

from assess import charts, proposal, render
from assess.content import ContentError, load_proposals
from assess.scoring import score

pytest.importorskip("reportlab")


# --- Профиль компании ----------------------------------------------------------


def test_company_loads(company):
    assert company.name == "Синимекс"
    assert company.organisation["founded"] == 1997
    assert company.offerings and company.proof and company.facts


def test_every_fact_names_a_known_source(company):
    for fact in company.facts:
        assert fact["source"] in company.sources, fact["id"]


def test_every_case_names_a_known_source_and_industry(company):
    for item in company.proof:
        assert item["source"] in company.sources, item["id"]
        for industry in item.get("industries", []):
            assert industry in company.industries


def test_perennial_facts_never_go_stale(company):
    stale = {item["id"] for item in company.stale_facts("2030-01-01")}
    assert "fsb" not in stale
    assert "founded" not in stale
    # А то, что живёт год, в 2030-м обязано попасть в список.
    assert "revenue" in stale


def test_proof_for_industry_prefers_matching_cases(company):
    banking = company.proof_for("banking", limit=3)
    assert banking
    assert any("banking" in item.get("industries", []) for item in banking)


def test_proof_for_unknown_industry_still_returns_cases(company):
    assert company.proof_for("нет-такой-отрасли", limit=2)


def test_company_page_lists_sources(company):
    page = render.company_page(company)
    for source in company.sources:
        assert source in page
    assert company.caveat in page


# --- Предложение ---------------------------------------------------------------


def test_example_proposal_loads(offer):
    assert offer.status == "final"
    assert offer.weeks == 16
    assert offer.assessment_id == "demo-retail-support"


def test_unknown_offering_is_rejected(write_proposal, company):
    def mutate(data):
        data["offerings"] = ["нет-такой-услуги"]

    with pytest.raises(ContentError) as error:
        load_proposals(write_proposal(mutate), company)
    assert any("нет услуги" in problem for problem in error.value.problems)


def test_unknown_case_in_about_is_rejected(write_proposal, company):
    def mutate(data):
        data["about"] = {"proof": ["мы-полетели-на-марс"]}

    with pytest.raises(ContentError) as error:
        load_proposals(write_proposal(mutate), company)
    assert any("нет кейса" in problem for problem in error.value.problems)


def test_unknown_industry_is_rejected(write_proposal, company):
    def mutate(data):
        data["client"]["industry"] = "космос"

    with pytest.raises(ContentError) as error:
        load_proposals(write_proposal(mutate), company)
    assert any("неизвестная отрасль" in problem for problem in error.value.problems)


def test_final_requires_a_gate_on_every_stage(write_proposal, company):
    def mutate(data):
        del data["stages"][1]["gate"]

    with pytest.raises(ContentError) as error:
        load_proposals(write_proposal(mutate), company)
    assert any("условие перехода" in problem for problem in error.value.problems)


def test_draft_may_skip_commercials(write_proposal, company):
    def mutate(data):
        data["status"] = "draft"
        data.pop("commercials")
        data.pop("team")
        for stage in data["stages"]:
            stage.pop("gate", None)
            stage.pop("price", None)

    loaded = load_proposals(write_proposal(mutate), company)
    assert len(loaded) == 1


# --- Разделы -------------------------------------------------------------------


def book(offer, company, result=None):
    return proposal.ProposalBook(offer, company, None, assessment=result)


def test_proposal_has_every_part(offer, company):
    titles = [title for title, _ in book(offer, company).content_parts()]
    assert titles[0] == "Что мы предлагаем"
    assert titles[-1] == "Следующие шаги"
    assert f"О компании {company.name}" in titles


def test_proposal_next_steps_include_contact_card(offer, company):
    parts = dict(book(offer, company).content_parts())
    text = "\n".join(parts["Следующие шаги"])
    assert "Контакты" in text
    for contact in company.contacts_for():
        assert contact["name"] in text
        assert contact["email"] in text


def test_about_section_carries_the_caveat(offer, company):
    text = "\n".join(
        line
        for title, body in book(offer, company).content_parts()
        if "О компании" in title
        for line in body
    )
    assert company.caveat in text
    assert company.organisation["positioning"] in text


def test_about_section_matches_the_client_industry(offer, company):
    text = "\n".join(
        line
        for title, body in book(offer, company).content_parts()
        if "О компании" in title
        for line in body
    )
    assert company.industries["banking"]["name"].lower() in text.lower()


def test_assessment_findings_reach_the_proposal(offer, company, examples, rubric):
    result = score(next(item for item in examples if item.id == offer.assessment_id), rubric)
    with_link = "\n".join(
        line
        for title, body in book(offer, company, result).content_parts()
        if title == "Понимание задачи"
        for line in body
    )
    assert result.verdict["name"] in with_link
    assert "Что показало обследование" in with_link
    without = "\n".join(
        line
        for title, body in book(offer, company).content_parts()
        if title == "Понимание задачи"
        for line in body
    )
    assert "Что показало обследование" not in without


def test_missing_assessment_link_is_reported(offer, company):
    notes = book(offer, company).warnings()
    assert any("не найдена" in note for note in notes)


def test_proposal_markup_stays_inside_the_renderer_subset(offer, company):
    import re

    page = render.proposal_page(offer, company)
    tags = {tag.lower() for tag in re.findall(r"<\s*(/?[a-zA-Z]+)", page)}
    assert tags <= {"picture", "source", "img", "/picture"}


# --- Печать --------------------------------------------------------------------


def test_timeline_figure_covers_every_stage(offer):
    svg = charts.timeline(offer, "light")
    for stage in offer.stages:
        assert stage["name"] in svg
    assert "<style" not in svg


def test_build_writes_pdf_and_manifest(tmp_path, offer, company):
    manifests = proposal.build([offer], company, tmp_path, tmp_path / "нет-фигур")
    manifest = manifests[0]
    assert manifest["document"] == "proposal"
    assert manifest["client"] == offer.client_name
    assert manifest["pages"] > 5
    assert manifest["checks"]["placeholder_left"] is False
    assert (tmp_path / manifest["output"]).is_file()


def test_file_name_does_not_double_the_suffix(offer):
    assert proposal.file_name(offer).count("-kp") == 1


def test_price_glyphs_are_substituted(offer, company):
    assert "₽" not in book(offer, company).markdown()
    assert "₽" not in book(offer, company).cover_text()
