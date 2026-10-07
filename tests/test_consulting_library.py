"""Library links and portable lookup must survive growth and moving the skill."""

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "consulting-presentations"
SPEC = importlib.util.spec_from_file_location(
    "consulting_library", SKILL / "scripts" / "library.py"
)
LIBRARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIBRARY)
CATALOG = json.loads((SKILL / "library" / "catalog.json").read_text(encoding="utf-8"))


def test_registry_and_lookup_keep_management_and_visual_distinct():
    assert LIBRARY.validate(CATALOG, SKILL) == []
    russian = LIBRARY.search(CATALOG, "прогноз", "management", "document")
    english = LIBRARY.search(CATALOG, "forecast", "visual", "slides")
    assert "M03" in [item["id"] for item in russian]
    assert "V03" in [item["id"] for item in english]
    assert all(item["kind"] == "management" for item in russian)
    assert LIBRARY.search(CATALOG, "V02", None, None)[0]["id"] == "V02"


def test_bad_links_and_duplicate_ids_are_reported():
    broken = copy.deepcopy(CATALOG)
    broken["entries"][0]["related"].append("V999")
    broken["entries"][0]["sources"].append("R999")
    broken["entries"].append(copy.deepcopy(broken["entries"][0]))
    errors = LIBRARY.validate(broken, SKILL)
    assert any("duplicate entry" in message for message in errors)
    assert any("unknown related id V999" in message for message in errors)
    assert any("unknown source R999" in message for message in errors)


def test_reference_cannot_escape_portable_pack(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("A real file is not a pack resource.")
    broken = copy.deepcopy(CATALOG)
    broken["entries"][0]["reference"] = str(outside)
    assert any("unsafe recipe reference" in message for message in LIBRARY.validate(broken, SKILL))


def test_verified_format_requires_implementation():
    broken = copy.deepcopy(CATALOG)
    broken["entries"][0]["verified_formats"] = ["docx"]
    assert any("lacks an example script" in message for message in LIBRARY.validate(broken, SKILL))


def test_library_runs_after_pack_is_moved_without_repo_dependencies(tmp_path):
    moved = tmp_path / "portable" / "consulting-presentations"
    shutil.copytree(SKILL, moved, ignore=shutil.ignore_patterns("__pycache__"))
    result = subprocess.run(
        [sys.executable, str(moved / "scripts" / "library.py"), "search", "ворота", "--json"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )
    found = json.loads(result.stdout)
    assert {"M04", "V02"} <= {item["id"] for item in found}


def test_style_overlays_keep_geometry_and_content_independent():
    geometry = json.loads((SKILL / "assets" / "format-profiles.json").read_text())
    neutral = json.loads((SKILL / "assets" / "styles" / "neutral.json").read_text())
    cinimex = json.loads((SKILL / "assets" / "styles" / "cinimex.json").read_text())

    def keys(value):
        if isinstance(value, dict):
            for name, child in value.items():
                yield name.casefold()
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    assert not {"colors", "font", "typography", "brand"} & set(keys(geometry))
    for style in (neutral, cinimex):
        assert not {"position", "bounds", "columnwidths", "rowheights", "slidesize"} & set(
            keys(style)
        )
        assert set(style["typography"]) == {"slides", "document"}
    assert set(neutral["colors"]) == set(cinimex["colors"])
    assert neutral["colors"] != cinimex["colors"]
