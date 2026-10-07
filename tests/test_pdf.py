"""Печать отчёта: оглавление сходится, глифы есть, ресурсы не выходят за каталог."""

import json

import pytest

from assess import pdf, pdf_render

pytest.importorskip("reportlab")


def test_book_markdown_has_one_h1_per_part(result):
    book = pdf.AssessmentBook(result, None)
    markdown = book.markdown()
    assert markdown.count("\n# ") + markdown.startswith("# ") == book.part_count()


def test_contents_starts_with_placeholders(result):
    book = pdf.AssessmentBook(result, None)
    assert pdf.PLACEHOLDER in book.markdown()


def test_brief_drops_the_methodology_and_the_sources(result):
    titles = {title for title, _ in pdf.AssessmentBook(result, None, brief=True).content_parts()}
    assert "Методология и шкала" not in titles
    assert "Резюме для руководства" in titles


@pytest.mark.parametrize("brief", [False, True])
def test_assessment_markdown_keeps_contacts_and_tracks_the_profile(result, company, brief):
    book = pdf.AssessmentBook(result, None, brief=brief)
    assert "Контакты" in {title for title, _ in book.content_parts()}
    for contact in company.contacts_for():
        assert contact["email"] in book.markdown()
    assert pdf.CONTENT / "company.yaml" in book.inputs()


def test_substitution_removes_characters_the_font_lacks(result):
    assert "₽" not in pdf.AssessmentBook(result, None).markdown()


def test_font_has_every_glyph_of_the_book(result):
    book = pdf.AssessmentBook(result, None)
    regular, bold = pdf_render.font_files(None)
    body = book.markdown() + book.cover_text()
    assert pdf_render.missing_glyphs(body, regular) == []
    assert pdf_render.missing_glyphs(body, bold) == []


def test_build_writes_pdf_markdown_and_manifest(tmp_path, result):
    manifests = pdf.build([result], tmp_path, tmp_path / "нет-фигур")
    assert len(manifests) == 1
    manifest = manifests[0]
    name = manifest["output"]
    assert (tmp_path / name).is_file()
    assert (tmp_path / f"{name}.md").is_file()
    stored = json.loads((tmp_path / f"{name}.manifest.json").read_text(encoding="utf-8"))
    assert stored == manifest
    assert manifest["pages"] > 5
    assert manifest["verdict"] == result.verdict["id"]


def test_contents_page_numbers_match_the_rendered_outline(tmp_path, result):
    manifest = pdf.build([result], tmp_path, tmp_path / "нет-фигур")[0]
    data = (tmp_path / manifest["output"]).read_bytes()
    pages = pdf_render.part_pages(data)
    # Первая закладка — оглавление, дальше части в том же порядке.
    assert [row["page"] for row in manifest["contents"]] == pages[1:]
    assert all(row["page"] > 1 for row in manifest["contents"])


def test_rendered_text_keeps_no_placeholder(tmp_path, result):
    manifest = pdf.build([result], tmp_path, tmp_path / "нет-фигур")[0]
    assert manifest["checks"]["placeholder_left"] is False
    text = pdf_render.extract_text((tmp_path / manifest["output"]).read_bytes())
    assert result.assessment.client in text
    assert "Конфиденциально" in text


def test_missing_figures_do_not_stop_the_build(tmp_path, result):
    book = pdf.AssessmentBook(result, tmp_path)
    assert book.figure("radar.ничего", "подпись") == []


def test_image_outside_the_build_directory_is_refused(tmp_path):
    inside = tmp_path / "assets"
    inside.mkdir()
    with pytest.raises(ValueError):
        pdf_render.render_markdown(
            "# Документ\n\n![](../секрет.png)\n",
            source_dir=inside,
            resource_root=inside,
        )


def test_remote_image_is_refused(tmp_path):
    with pytest.raises(ValueError):
        pdf_render.render_markdown(
            "# Документ\n\n![](https://example.com/a.png)\n",
            source_dir=tmp_path,
            resource_root=tmp_path,
        )


def test_column_widths_fit_the_frame_and_the_longest_word():
    texts = [["Измерение", "Вес"], ["Безопасность, ПДн и соответствие", "3"]]
    font, _ = pdf_render.fonts(None)
    widths = pdf_render._column_widths(texts, 2, 400, font, 10)
    assert sum(widths) == pytest.approx(400, abs=1)
    assert widths[0] > widths[1]


def test_font_size_outside_the_range_is_refused():
    with pytest.raises(ValueError):
        pdf_render.Styles(None, 42)
