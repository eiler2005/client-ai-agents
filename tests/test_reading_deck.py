"""Content validation and OOXML verification without the optional Node runtime."""

import copy
import importlib.util
import json
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_reading_deck.py"
module_spec = importlib.util.spec_from_file_location("build_reading_deck", SCRIPT)
reading = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(reading)


@pytest.fixture
def spec(company):
    return {
        "slides": [
            {
                "number": 1,
                "title": "Example project",
                "layout": "cover",
                "contact_id": company.contacts[0]["id"],
                "blocks": [{"heading": "Scope", "body": "Verified catalogue consultation."}],
                "takeaway": "Agree the pilot.",
                "notes": "This is an invented test project.",
            }
        ]
    }


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"number": 2}, "sequential"),
        ({"number": True}, "sequential"),
        ({"layout": "unknown"}, "unsupported layout"),
        ({"layout": "matrix"}, "first slide"),
        ({"contact_id": "unknown"}, "unknown contact_id"),
        ({"company_facts": ["unknown"]}, "unknown company_facts"),
        ({"company_proof": ["unknown"]}, "unknown company_proof"),
        ({"blocks": [{"heading": "Incomplete"}]}, "heading and body"),
    ],
)
def test_invalid_content_stops_before_rendering(spec, company, change, message):
    spec["slides"][0].update(change)
    with pytest.raises(ValueError, match=message):
        reading.validate_spec(spec, company, {"diagrams": []})


def test_unknown_diagram_reference_is_rejected(spec, company):
    spec["slides"].append(
        {
            "number": 2,
            "title": "Architecture",
            "layout": "diagram",
            "blocks": [],
            "diagram_key": "missing",
        }
    )
    with pytest.raises(ValueError, match="unknown diagram_key"):
        reading.validate_spec(spec, company, {"diagrams": []})


@pytest.mark.parametrize("page_range", [{"start": 3, "end": 3}, {"start": 2, "end": 1}])
def test_contents_cannot_point_outside_deck_or_reverse_range(spec, company, page_range):
    spec["slides"].append(
        {
            "number": 2,
            "title": "Contents",
            "layout": "contents",
            "blocks": [{"heading": "Summary", "body": "Proposal and decisions."}],
            "contents_ranges": [page_range],
        }
    )
    with pytest.raises(ValueError, match="outside the deck or reversed"):
        reading.validate_spec(spec, company, {"diagrams": []})


def test_contents_page_labels_are_part_of_visible_text_check(spec, company):
    spec["slides"].append(
        {
            "number": 2,
            "title": "Contents",
            "layout": "contents",
            "blocks": [{"heading": "Overview", "body": "Proposal and decisions."}],
            "contents_ranges": [{"start": 1, "end": 2}],
        }
    )
    reading.validate_spec(spec, company, {"diagrams": []})
    required = reading.required_text(spec["slides"][1], company, {})
    assert ("contents range 1", "01–02") in required
    extracted = [
        {
            "text": "\n".join(value for _, value in reading.required_text(s, company, {})),
            "notes": s.get("notes", ""),
        }
        for s in spec["slides"]
    ]
    assert reading.verify_text(spec, company, {}, extracted)["passed"]
    extracted[1]["text"] = extracted[1]["text"].replace("01–02", "01–03")
    assert not reading.verify_text(spec, company, {}, extracted)["passed"]


def test_payload_resolves_profile_contacts_without_changing_canonical_spec(spec, company):
    original = copy.deepcopy(spec)
    reading.validate_spec(spec, company, {"diagrams": []})
    payload = reading.prepare_payload(spec, company)
    assert spec == original
    assert payload["company"] == company.data
    assert payload["contacts"] == [company.contacts[0]]
    assert company.contacts[0]["name"] in reading.markdown_companion(payload)
    assert "contacts" not in spec


def test_comparison_cell_cannot_be_hidden_in_notes(spec, company):
    slide = {
        "number": 2,
        "title": "Explain the selection",
        "layout": "annotated-choice",
        "blocks": [
            {"heading": "Need", "body": "Confirm the operating conditions."},
            {"heading": "Result", "body": "Explain the supported options."},
            {"heading": "Gap", "body": "Ask for missing evidence."},
        ],
        "visual_copy": {
            "caption": "Illustrative example",
            "rows": [["Connection", "Confirmed", "No catalogue evidence"]],
        },
    }
    spec["slides"].append(slide)
    reading.validate_spec(spec, company, {"diagrams": []})
    extracted = [
        {
            "text": "\n".join(t for _, t in reading.required_text(s, company, {})),
            "notes": s.get("notes", ""),
        }
        for s in spec["slides"]
    ]
    assert reading.verify_text(spec, company, {}, extracted)["passed"]
    extracted[1]["text"] = extracted[1]["text"].replace("No catalogue evidence", "")
    extracted[1]["notes"] = "No catalogue evidence"
    check = reading.verify_text(spec, company, {}, extracted)
    assert not check["passed"]
    assert any("No catalogue evidence" in item for item in check["missing"])


def test_visible_text_cannot_be_replaced_by_speaker_notes(spec, company):
    slide = spec["slides"][0]
    full = "\n".join(text for _, text in reading.required_text(slide, company, {}))
    actual = [{"text": slide["title"], "notes": slide["notes"] + "\n" + full}]
    check = reading.verify_text(spec, company, {}, actual)
    assert not check["passed"]
    assert any("block 1 body" in item for item in check["missing"])
    actual[0]["text"] = full.replace("Verified", "Veri\nfied")
    assert reading.verify_text(spec, company, {}, actual)["passed"]
    actual[0]["text"] = full.replace("Verified", "Unverified")
    assert not reading.verify_text(spec, company, {}, actual)["passed"]


def test_explicit_cover_copy_keeps_full_logical_content_in_notes(spec, company):
    slide = spec["slides"][0]
    slide.update(cover_display_title="Project", cover_description="Catalogue advice")
    full_notes = "\n".join([slide["notes"], slide["title"], *slide["blocks"][0].values()])
    visible = f"Project\nCatalogue advice\n{company.contacts[0]['name']}"
    assert reading.verify_text(spec, company, {}, [{"text": visible, "notes": full_notes}])[
        "passed"
    ]
    check = reading.verify_text(spec, company, {}, [{"text": visible, "notes": slide["notes"]}])
    assert not check["passed"]


def test_diagram_labels_and_missing_slides_fail_verification(spec, company):
    slide = {
        "number": 2,
        "title": "Architecture",
        "layout": "diagram",
        "blocks": [],
        "diagram_key": "architecture",
    }
    spec["slides"].append(slide)
    diagrams = {
        "diagrams": [
            {
                "id": "architecture",
                "nodes": [{"title": "Catalog"}],
                "edges": [{"label": "Confirmed data"}],
            }
        ]
    }
    first_text = "\n".join(t for _, t in reading.required_text(spec["slides"][0], company, {}))
    actual = [{"text": first_text, "notes": spec["slides"][0]["notes"]}]
    assert "slide count" in reading.verify_text(spec, company, diagrams, actual)["missing"][0]
    actual.append({"text": "Architecture\nCatalog", "notes": ""})
    check = reading.verify_text(spec, company, diagrams, actual)
    assert any("edges 1 label" in item for item in check["missing"])


def test_xml_extraction_uses_relationships_and_presentation_order(tmp_path):
    pptx = tmp_path / "test.pptx"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    r = reading.NS["r"]

    def rels(entries):
        return (
            f'<Relationships xmlns="{rel_ns}">'
            + "".join(
                f'<Relationship Id="{id_}" Type="{r}/{kind}" Target="{target}"/>'
                for id_, kind, target in entries
            )
            + "</Relationships>"
        )

    def content(text):
        return (
            f'<root xmlns:a="{reading.NS["a"]}"><a:p><a:r><a:t>{escape(text)}</a:t>'
            "</a:r></a:p></root>"
        )

    with ZipFile(pptx, "w") as archive:
        archive.writestr(
            "ppt/presentation.xml",
            f'<p:presentation xmlns:p="{reading.NS["p"]}" '
            f'xmlns:r="{r}"><p:sldIdLst><p:sldId r:id="second"/>'
            '<p:sldId r:id="first"/></p:sldIdLst></p:presentation>',
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            rels(
                [
                    ("first", "slide", "slides/slide1.xml"),
                    ("second", "slide", "slides/slide9.xml"),
                ]
            ),
        )
        archive.writestr("ppt/slides/slide1.xml", content("Second visible"))
        archive.writestr("ppt/slides/slide9.xml", content("First visible"))
        archive.writestr(
            "ppt/slides/_rels/slide9.xml.rels",
            rels(
                [
                    ("notes", "notesSlide", "../notesSlides/notesSlide4.xml"),
                ]
            ),
        )
        archive.writestr("ppt/notesSlides/notesSlide4.xml", content("Notes & evidence"))
    assert reading.extract_text(pptx) == [
        {"text": "First visible", "notes": "Notes & evidence"},
        {"text": "Second visible", "notes": ""},
    ]


def test_manifest_update_preserves_manual_review_gate_and_other_fields(tmp_path):
    path = tmp_path / "deck.manifest.json"
    original = {"hash": "unchanged", "checks": {"visual_review": False, "geometry": True}}
    path.write_text(json.dumps(original))
    reading.update_manifest(path, {"passed": True})
    updated = json.loads(path.read_text())
    assert updated == {
        **original,
        "checks": {**original["checks"], "text_extraction": {"passed": True}},
    }
    updated["checks"]["visual_review"] = True
    path.write_text(json.dumps(updated))
    with pytest.raises(ValueError, match="visual_review=false"):
        reading.update_manifest(path, {"passed": True})


def test_deliverables_cannot_be_written_next_to_committed_spec(tmp_path):
    with pytest.raises(ValueError, match="ignored dist"):
        reading.resolve_output(tmp_path / "docs/reading.pptx", root=tmp_path)
