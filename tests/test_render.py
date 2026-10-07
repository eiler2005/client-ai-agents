"""Разметка страниц и фигуры: подмножество Markdown и безопасность SVG."""

import re

from assess import charts, render
from assess.scoring import score

ALLOWED_HTML = {"picture", "source", "img", "/picture"}


def test_report_page_has_every_part(result):
    page = render.report_page(result)
    for title in ("Резюме для руководства", "Оценка по измерениям", "Методология и шкала"):
        assert f"## {title}" in page


def test_report_page_states_the_verdict_and_the_score(result):
    page = render.report_page(result)
    assert result.verdict["name"] in page
    assert f"{result.overall:.0f} из 100" in page


def test_client_pages_include_default_contact_channels(result, offer, company):
    for page in (render.report_page(result), render.proposal_page(offer, company, result)):
        assert "Контакты" in page
        for contact in company.contacts_for():
            assert contact["name"] in page
            assert contact["role"] in page
            for channel in ("phone", "email", "telegram"):
                if contact.get(channel):
                    assert contact[channel] in page


def test_report_markup_stays_inside_the_renderer_subset(result):
    page = render.report_page(result)
    tags = {tag.lower() for tag in re.findall(r"<\s*(/?[a-zA-Z]+)", page)}
    assert tags <= ALLOWED_HTML


def test_draft_report_says_the_verdict_is_provisional(examples, rubric):
    draft = next(item for item in examples if item.status == "draft")
    page = render.report_page(score(draft, rubric))
    assert "предварительная оценка" in page


def test_criteria_follow_the_rubric_order(result, rubric):
    page = render.report_page(result)
    names = [item["name"] for item in rubric.by_id["business-value"]["criteria"]]
    line = next(line for line in page.splitlines() if line.startswith("**По критериям:**"))
    positions = [line.index(name) for name in names]
    assert positions == sorted(positions)


def test_rubric_page_lists_every_dimension(rubric):
    page = render.rubric_page(rubric)
    for dimension in rubric.dimensions:
        assert dimension["name"] in page


def test_portfolio_page_links_each_report(examples, rubric):
    results = [score(item, rubric) for item in examples]
    page = render.portfolio_page(results, rubric)
    for result in results:
        assert f"reports/{result.assessment.id}.md" in page


def test_figures_carry_no_css(result):
    for mode in charts.MODES:
        for svg in (
            charts.radar(result, mode),
            charts.scorecard(result, mode),
            charts.risk_matrix(result, mode),
        ):
            assert "<style" not in svg
            assert "@import" not in svg
            assert "url(" not in svg
            assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")


def test_figures_have_a_title_and_a_description(result):
    svg = charts.radar(result, "light")
    assert "<title>" in svg and "<desc>" in svg


def test_radar_marks_unscored_dimensions(examples, rubric):
    draft = next(item for item in examples if item.status == "draft")
    svg = charts.radar(score(draft, rubric), "light")
    assert "—" in svg
    assert "контур по таким осям не замкнут" in svg


def test_write_figures_produces_a_light_and_a_dark_file(tmp_path, examples, rubric):
    results = [score(item, rubric) for item in examples]
    written = charts.write_figures(tmp_path, results, rubric)
    names = {path.name for path in written}
    assert f"radar.{results[0].assessment.id}.svg" in names
    assert f"radar.{results[0].assessment.id}.dark.svg" in names
    assert "portfolio.svg" in names


def test_write_docs_generates_pages(tmp_path, examples, rubric):
    results = [score(item, rubric) for item in examples]
    written = render.write_docs(tmp_path, results, rubric)
    assert (tmp_path / "RUBRIC.md") in written
    assert (tmp_path / "PORTFOLIO.md").is_file()
    assert (tmp_path / "reports" / f"{results[0].assessment.id}.md").is_file()
    assert "assess build" in (tmp_path / "RUBRIC.md").read_text(encoding="utf-8")
