"""Презентация сохраняет смысл оценки и проверяемость коммерческих утверждений."""

import hashlib
import json
import os
import posixpath
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from assess import slides
from assess.cli import main
from assess.content import CONTENT, ContentError, Proposal, validate
from assess.scoring import score


def test_deck_uses_the_capped_verdict_and_actual_coverage(result, company):
    deck = slides.assessment_deck(result, company)
    summary = next(part for part in deck["slides"] if part["kind"] == "summary")
    assert summary["title"] == result.verdict["name"]
    assert summary["metrics"][0][0] == f"{result.overall:.0f}/100"
    assert summary["metrics"][1][0] == f"{result.coverage:.0f}%"
    assert summary["metrics"][2][0] == str(len(result.blockers))
    assert deck["references"] == result.assessment.sources


def test_draft_preserves_unscored_dimensions(examples, rubric, company):
    result = score(next(item for item in examples if item.status == "draft"), rubric)
    deck = slides.assessment_deck(result, company)
    assert "Предварительно" in deck["slides"][1]["title"]
    dimensions = [
        item for part in deck["slides"] if part["kind"] == "score" for item in part["dimensions"]
    ]
    assert [item["level"] for item in dimensions] == [item.level for item in result.dimensions]
    assert any(item["level"] is None for item in dimensions)


def test_no_scored_dimensions_do_not_display_zero_readiness(make_assessment, rubric, company):
    result = score(make_assessment(status="draft", scores={}), rubric)
    assert slides.assessment_deck(result, company)["slides"][1]["metrics"][0][0] == "—"


def test_proposal_keeps_commercials_gates_contacts_and_effect_caveat(offer, company, result):
    deck = slides.proposal_deck(offer, company, result)
    parts = deck["slides"]
    text = json.dumps(parts, ensure_ascii=False)
    assert offer.commercials["total"] in text
    assert offer.valid_until in text
    for stage in offer.stages:
        assert stage["gate"] in text
    for assumption in offer.commercials["assumptions"]:
        assert assumption in text
    assert parts[-1]["contacts"] == company.contacts_for()
    cases = [part for part in parts if part.get("headers") == ["Задача", "Результат"]]
    assert cases and all(part["caveat"] == company.caveat for part in cases)


def test_missing_linked_assessment_fails(offer, company):
    with pytest.raises(ContentError, match="проблем") as error:
        slides.proposal_deck(offer, company)
    assert "не найдена связанная оценка" in error.value.problems[0]


def test_proposal_without_assessment_still_builds_content(offer, company):
    data = {**offer.data, "project": {**offer.project}}
    data["project"].pop("assessment")
    standalone = Proposal(data, offer.path)
    assert slides.proposal_deck(standalone, company)["kind"] == "proposal"


def test_style_rejects_invalid_colors_and_tiny_fonts():
    style = slides.load_style()
    style["colors"]["accent"] = "red"
    style["typography"]["body"] = 8
    assert len(validate(style, "presentation.schema.json", "style")) == 2


def test_slide_command_reports_unknown_id(capsys):
    assert main(["--demo", "slides", "--only", "no-such-project"]) == 1
    assert "Не найдены" in capsys.readouterr().err


def test_missing_runtime_gives_actionable_error(tmp_path, monkeypatch, result, company):
    monkeypatch.setenv("CINIMEX_ARTIFACT_TOOL", str(tmp_path / "missing"))
    with pytest.raises(ContentError) as error:
        slides.build(slides.assessment_deck(result, company), tmp_path)
    assert "CINIMEX_ARTIFACT_TOOL" in error.value.problems[0]


def test_pptx_exports_editable_data_and_notes(tmp_path, result, company):
    runtime = Path(
        os.environ.get(
            "CINIMEX_ARTIFACT_TOOL",
            Path.home()
            / ".cache"
            / "codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
            / "@oai/artifact-tool",
        )
    )
    if not shutil.which("node") or not (runtime / "package.json").is_file():
        pytest.skip("Node.js и @oai/artifact-tool нужны только для интеграционной проверки PPTX")
    deck = slides.assessment_deck(result, company)
    table = next(part for part in deck["slides"] if part["kind"] == "table")
    chart = next(part for part in deck["slides"] if part["kind"] == "score")
    deck["slides"] = [table, chart, deck["slides"][-1]]
    manifest = slides.build(deck, tmp_path)
    output = tmp_path / manifest["output"]
    assert manifest["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert manifest["checks"]["visual_review"] is False
    assert manifest["checks"]["pdf_built"] is False
    assert not list(tmp_path.glob("*.pdf"))
    assert {item["name"] for item in manifest["inputs"]} >= {
        "rubric.yaml",
        "company.yaml",
        "presentation.yaml",
        "presentation.mjs",
    }
    with zipfile.ZipFile(output) as archive:
        charts = [
            name for name in archive.namelist() if "/charts/" in name and name.endswith(".xml")
        ]
        assert charts
        for name in archive.namelist():
            if name.endswith(".xml"):
                ET.fromstring(archive.read(name))
        native_table = ET.fromstring(archive.read("ppt/slides/slide1.xml"))
        assert (
            native_table.find(".//{http://schemas.openxmlformats.org/drawingml/2006/main}tbl")
            is not None
        )
        for name in archive.namelist():
            if name.endswith(".rels"):
                base = "" if name == "_rels/.rels" else posixpath.dirname(posixpath.dirname(name))
                for relationship in ET.fromstring(archive.read(name)):
                    if relationship.get("TargetMode") != "External":
                        target = posixpath.normpath(
                            posixpath.join(base, relationship.attrib["Target"])
                        ).lstrip("/")
                        assert target in archive.namelist(), (name, target)
        notes = "\n".join(
            "".join(ET.fromstring(archive.read(name)).itertext())
            for name in archive.namelist()
            if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml")
        )
        assert result.assessment.sources[0]["title"] in notes
        assert table["rows"][0][1] in notes
    assert (Path(manifest["workspace"]) / "preview" / "slide-01.png").is_file()
    assert (CONTENT / "presentation.yaml").name in {item["name"] for item in manifest["inputs"]}
