"""Build and verify a Cinimex Consulting reading deck from its canonical JSON.

Run with ``uv run python scripts/build_reading_deck.py --spec ... --out dist/...pptx``.
Generated client content stays in ignored dist/ and an external temporary workspace.
The renderer owns the manifest; this wrapper updates only checks.text_extraction.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from assess.content import Company, ContentError, load_company  # noqa: E402

LAYOUTS = {
    "cover",
    "three-column",
    "two-column",
    "scenario",
    "matrix",
    "timeline",
    "company",
    "decisions",
    "rows",
    "method-table",
    "diagram",
    "source-image",
    "gates",
    "contents",
    "executive-summary",
    "section-intro",
    "work-comparison",
    "context-diptych",
    "annotated-choice",
    "catalog-anatomy",
    "answer-evidence",
    "options-table",
    "value-tree",
    "acceptance-cases",
}
VISUAL_BLOCKS = {
    "work-comparison": 2,
    "context-diptych": 3,
    "annotated-choice": 3,
    "catalog-anatomy": 3,
    "answer-evidence": 4,
    "options-table": 2,
    "value-tree": 3,
    "acceptance-cases": 3,
}
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_spec(data: dict, company: Company, diagrams: dict) -> None:
    """Fail before rendering when content or company references are ambiguous."""
    slides = data.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValueError("spec.slides must be a non-empty array")
    diagram_list = diagrams.get("diagrams", [])
    if not isinstance(diagram_list, list) or any(not isinstance(d, dict) for d in diagram_list):
        raise ValueError("diagrams.diagrams must be an array of objects")
    diagram_ids = [d.get("id") for d in diagram_list]
    if any(not isinstance(d, str) or not d for d in diagram_ids):
        raise ValueError("each diagram needs a non-empty id")
    if len(set(diagram_ids)) != len(diagram_ids):
        raise ValueError("diagram ids must be unique")
    for number, slide in enumerate(slides, 1):
        label = f"slide {number}"
        if not isinstance(slide, dict):
            raise ValueError(f"{label}: expected an object")
        if type(slide.get("number")) is not int or slide["number"] != number:
            raise ValueError(f"{label}: numbering must be sequential from 1")
        layout = slide.get("layout")
        if not isinstance(layout, str) or layout not in LAYOUTS:
            raise ValueError(f"{label}: unsupported layout {layout!r}")
        if (number == 1) != (layout == "cover"):
            raise ValueError(f"{label}: only the first slide must use cover")
        if not isinstance(slide.get("title"), str) or not slide["title"].strip():
            raise ValueError(f"{label}: title must be non-empty text")
        for field in (
            "kicker",
            "subtitle",
            "takeaway",
            "notes",
            "cover_display_title",
            "cover_description",
            "section_label",
            "source_label",
        ):
            if field in slide and not isinstance(slide[field], str):
                raise ValueError(f"{label}: {field} must be text")
        blocks = slide.get("blocks")
        if not isinstance(blocks, list):
            raise ValueError(f"{label}: blocks must be an array")
        for block in blocks:
            if not isinstance(block, dict) or any(
                not isinstance(block.get(field), str) for field in ("heading", "body")
            ):
                raise ValueError(f"{label}: each block requires heading and body text")
        if layout in VISUAL_BLOCKS:
            visual = slide.get("visual_copy")
            if not isinstance(visual, dict) or not visual:
                raise ValueError(f"{label}: {layout} requires visual_copy")
            if len(blocks) != VISUAL_BLOCKS[layout]:
                raise ValueError(f"{label}: {layout} requires {VISUAL_BLOCKS[layout]} blocks")
            validate_visual_copy(visual, label)
        if layout == "context-diptych" and not isinstance(slide.get("image_path"), str):
            raise ValueError(f"{label}: context-diptych requires image_path")
        if layout == "contents":
            ranges = slide.get("contents_ranges", [])
            if len(ranges) != len(blocks):
                raise ValueError(f"{label}: each contents entry requires a slide range")
            for item in ranges:
                if (
                    not isinstance(item, dict)
                    or type(item.get("start")) is not int
                    or type(item.get("end")) is not int
                    or not 1 <= item["start"] <= item["end"] <= len(slides)
                ):
                    raise ValueError(f"{label}: contents range is outside the deck or reversed")
        for key, index in (("company_facts", company.by_fact), ("company_proof", company.by_proof)):
            refs = slide.get(key, [])
            if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                raise ValueError(f"{label}: {key} must contain ids")
            for ref in refs:
                if ref not in index:
                    raise ValueError(f"{label}: unknown {key} id {ref!r}")
        contact_id = slide.get("contact_id")
        if number == 1 and not contact_id:
            raise ValueError("slide 1: cover requires contact_id from company.yaml")
        if contact_id is not None and (
            not isinstance(contact_id, str) or contact_id not in company.by_contact
        ):
            raise ValueError(f"{label}: unknown contact_id {contact_id!r}")
        if layout == "diagram" and slide.get("diagram_key") not in diagram_ids:
            raise ValueError(f"{label}: unknown diagram_key {slide.get('diagram_key')!r}")
        if layout == "source-image" and not isinstance(slide.get("image_path"), str):
            raise ValueError(f"{label}: source-image requires image_path")
        for field in ("cover_image", "image_path"):
            if slide.get(field) and not (ROOT / slide[field]).is_file():
                raise ValueError(f"{label}: missing {field}: {slide[field]}")


def validate_visual_copy(value, label: str) -> None:
    """Visual labels are client-visible copy and participate in text verification."""
    if isinstance(value, str) and value.strip():
        return
    if isinstance(value, (dict, list)) and value:
        items = value.values() if isinstance(value, dict) else value
        for item in items:
            validate_visual_copy(item, label)
        return
    raise ValueError(f"{label}: visual_copy must contain non-empty text, lists or objects")


def resolve_output(out: Path, root: Path = ROOT) -> Path:
    """Keep the companion containing profile contacts under the ignored dist tree."""
    out = out.expanduser().resolve()
    if out.suffix.lower() != ".pptx" or not out.is_relative_to((root / "dist").resolve()):
        raise ValueError("--out must be a .pptx inside the repository's ignored dist/ directory")
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", str(out.with_suffix(".md"))],
        cwd=root,
        check=False,
    )
    if ignored.returncode != 0:
        raise ValueError("the Markdown companion must be ignored by git")
    return out


def find_skill(explicit: Path | None = None) -> Path:
    configured = explicit or os.environ.get("CINIMEX_PRESENTATION_SKILL")
    if configured:
        candidates = [Path(configured).expanduser().resolve()]
    else:
        base = Path.home() / ".codex/plugins/cache/openai-primary-runtime/presentations"
        candidates = sorted(
            base.glob("*/skills/presentations"),
            key=lambda p: tuple(int(n) for n in re.findall(r"\d+", p.parents[1].name)),
            reverse=True,
        )
    for candidate in candidates:
        scripts = candidate / "template_following_scripts"
        if all(
            (scripts / name).is_file()
            for name in ("inspect_template_deck.mjs", "prepare_template_starter_deck.mjs")
        ):
            return candidate
    raise ValueError(
        "Presentations skill not found; use --presentation-skill or CINIMEX_PRESENTATION_SKILL"
    )


def prepare_payload(spec: dict, company: Company) -> dict:
    payload = copy.deepcopy(spec)
    chosen = list(dict.fromkeys(s["contact_id"] for s in spec["slides"] if s.get("contact_id")))
    payload["contacts"] = company.contacts_for(chosen)
    payload["company"] = company.data
    return payload


def markdown_companion(payload: dict, diagrams: dict | None = None) -> str:
    sections = []
    contacts = {contact["id"]: contact for contact in payload["contacts"]}
    for slide in payload["slides"]:
        lines = [f"# {slide['number']}. {slide['title']}"]
        if slide.get("subtitle"):
            lines.append(slide["subtitle"])
        for block in slide["blocks"]:
            lines.extend([f"## {block['heading']}", block["body"]])
        if slide.get("visual_copy"):
            lines.extend(["## Содержание визуализации", *strings(slide["visual_copy"])])
        if slide.get("diagram_key") and diagrams:
            diagram = next(d for d in diagrams["diagrams"] if d["id"] == slide["diagram_key"])
            lines.append("## Схема решения")
            for node in diagram["nodes"]:
                title = node["title"]
                if isinstance(title, list):
                    title = " ".join(title)
                lines.append(f"- **{title}**: {'; '.join(node.get('subtitle', []))}")
            names = {
                node["id"]: " ".join(node["title"])
                if isinstance(node["title"], list)
                else node["title"]
                for node in diagram["nodes"]
            }
            for edge in diagram["edges"]:
                label = edge.get("label") or ""
                if isinstance(label, list):
                    label = " ".join(label)
                ending = " (пунктир: вариант или исключение)" if edge.get("dashed") else ""
                lines.append(
                    f"- {names[edge['source']]} → {names[edge['target']]}"
                    f"{': ' + label if label else ''}{ending}"
                )
            lines.append(diagram["footer"])
        if slide.get("image_path"):
            lines.append(f"Исходная схема: `{slide['image_path']}`.")
        if slide.get("takeaway"):
            lines.append(f"**{slide['takeaway']}**")
        if slide.get("contact_id"):
            contact = contacts[slide["contact_id"]]
            lines.extend(
                contact[key]
                for key in ("name", "role", "unit", "email", "phone", "telegram")
                if contact.get(key)
            )
        if slide.get("notes"):
            lines.extend(["## Заметки", slide["notes"]])
        if slide.get("sources"):
            lines.append("## Источники")
            for source in slide["sources"]:
                url = f" — {source['url']}" if source.get("url") else ""
                lines.append(f"- {source['title']} ({source.get('date', '')}){url}")
        sections.append("\n\n".join(lines))
    return "\n\n---\n\n".join(sections) + "\n"


def relationships(archive: ZipFile, part: str) -> dict[str, tuple[str, str]]:
    parent, name = posixpath.split(part)
    rels = posixpath.join(parent, "_rels", name + ".rels")
    if rels not in archive.namelist():
        return {}
    result = {}
    for element in ET.fromstring(archive.read(rels)):
        if element.get("TargetMode") == "External":
            continue
        target = element.attrib["Target"]
        resolved = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join(parent, target))
        )
        result[element.attrib["Id"]] = (element.attrib["Type"], resolved)
    return result


def xml_text(xml: bytes) -> str:
    root = ET.fromstring(xml)
    return "\n".join(
        "".join(node.text or "" for node in paragraph.findall(".//a:t", NS))
        for paragraph in root.findall(".//a:p", NS)
    )


def extract_text(pptx: Path) -> list[dict[str, str]]:
    """Use presentation order and per-slide relationships, including speaker notes."""
    with ZipFile(pptx) as archive:
        presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
        rels = relationships(archive, "ppt/presentation.xml")
        slides = []
        for element in presentation.findall("p:sldIdLst/p:sldId", NS):
            _, part = rels[element.attrib[f"{{{NS['r']}}}id"]]
            notes = [
                target
                for kind, target in relationships(archive, part).values()
                if kind.endswith("/notesSlide")
            ]
            slides.append(
                {
                    "text": xml_text(archive.read(part)),
                    "notes": "\n".join(xml_text(archive.read(target)) for target in notes),
                }
            )
        return slides


def strings(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [text for item in value for text in strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in strings(item)]
    return []


def required_text(slide: dict, company: Company, diagrams: dict) -> list[tuple[str, str]]:
    if slide["layout"] == "cover" and slide.get("cover_display_title"):
        fields = ("cover_display_title", "cover_description", "subtitle")
        expected = [(key, slide[key]) for key in fields if slide.get(key)]
    else:
        fields = ("title", "subtitle", "takeaway", "section_label", "source_label")
        expected = [(key, slide[key]) for key in fields if slide.get(key)]
        for index, block in enumerate(slide["blocks"], 1):
            expected += [(f"block {index} {key}", block[key]) for key in ("heading", "body")]
        expected += [
            (f"visual copy {index}", text)
            for index, text in enumerate(strings(slide.get("visual_copy")), 1)
        ]
    if slide.get("contact_id"):
        expected.append(("contact name", company.by_contact[slide["contact_id"]]["name"]))
    for index, gate in enumerate(slide.get("gates", []), 1):
        expected += [
            (f"gate {index} {key}", value) for key, value in gate.items() if isinstance(value, str)
        ]
    for index, item in enumerate(slide.get("contents_ranges", []), 1):
        page_label = f"{item['start']:02}"
        if item["end"] != item["start"]:
            page_label += f"–{item['end']:02}"
        expected.append((f"contents range {index}", page_label))
    if slide["layout"] == "diagram":
        diagram = next(d for d in diagrams["diagrams"] if d["id"] == slide["diagram_key"])
        for group, fields in (
            ("nodes", ("title", "subtitle")),
            ("edges", ("label",)),
            ("callouts", ("text",)),
        ):
            for index, item in enumerate(diagram.get(group, []), 1):
                for field in fields:
                    expected += [
                        (f"{group} {index} {field}", text) for text in strings(item.get(field))
                    ]
        for field in ("footer",):
            expected += [(f"diagram {field}", text) for text in strings(diagram.get(field))]
    return expected


def text_present(expected: str, actual: str) -> bool:
    # Native text may wrap inside a word. Keep word boundaries: "verified" must
    # not match "unverified" even though whitespace and uppercase styling vary.
    compact = "".join(expected.split())
    if not compact:
        return True
    pattern = r"\s*".join(re.escape(character) for character in compact)
    if re.match(r"\w", compact[0]):
        pattern = r"(?<!\w)" + pattern
    if re.match(r"\w", compact[-1]):
        pattern += r"(?!\w)"
    return re.search(pattern, actual, re.IGNORECASE) is not None


def verify_text(spec: dict, company: Company, diagrams: dict, extracted: list[dict]) -> dict:
    missing = []
    if len(extracted) != len(spec["slides"]):
        missing.append(f"slide count: expected {len(spec['slides'])}, got {len(extracted)}")
    for slide, actual in zip(spec["slides"], extracted, strict=False):
        for label, expected in required_text(slide, company, diagrams):
            if not text_present(expected, actual["text"]):
                missing.append(f"slide {slide['number']}: {label}: {expected}")
        if slide.get("notes") and not text_present(slide["notes"], actual["notes"]):
            missing.append(f"slide {slide['number']}: canonical speaker notes")
        if slide["layout"] == "cover" and slide.get("cover_display_title"):
            hidden = [slide["title"]]
            hidden += [block[key] for block in slide["blocks"] for key in ("heading", "body")]
            for expected in hidden:
                if not text_present(expected, actual["notes"]):
                    missing.append(f"slide 1: logical cover text in notes: {expected}")
    return {
        "passed": not missing,
        "slide_count": len(extracted),
        "missing": missing,
        "full_visible_copy": "all non-cover blocks + explicit cover display fields; "
        "logical cover title/blocks retained in notes",
        "normalization": "whitespace and case only; no truncation or punctuation removal",
    }


def update_manifest(path: Path, check: dict) -> None:
    manifest = read_json(path)
    checks = manifest.setdefault("checks", {})
    # Never carry a prior manual approval onto a freshly rendered artifact.
    if checks.get("visual_review") is not False:
        raise ValueError("renderer manifest must start with checks.visual_review=false")
    checks["text_extraction"] = check
    write_json(path, manifest)


def run_node(script: Path, *args: str | Path, workspace: Path) -> None:
    subprocess.run(["node", str(script), *(str(arg) for arg in args)], cwd=workspace, check=True)


def build(spec_path: Path, out: Path, diagrams_path: Path | None, skill: Path) -> dict:
    spec_path = spec_path.expanduser().resolve()
    out = resolve_output(out)
    spec = read_json(spec_path)
    company = load_company(ROOT / "src/content")
    diagrams_path = diagrams_path or spec_path.with_name("diagrams.json")
    diagrams = read_json(diagrams_path) if diagrams_path.is_file() else {"diagrams": []}
    validate_spec(spec, company, diagrams)
    workspace = Path(tempfile.mkdtemp(prefix="cinimex-reading-"))
    if workspace.resolve().is_relative_to(ROOT):
        workspace.rmdir()
        raise ValueError("system temporary directory must be outside the repository")
    print(f"Workspace: {workspace}", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = prepare_payload(spec, company)
    payload_path = workspace / "payload.json"
    write_json(payload_path, payload)
    if not diagrams_path.is_file():
        diagrams_path = workspace / "diagrams.json"
        write_json(diagrams_path, diagrams)
    diagrams_path = diagrams_path.resolve()
    out.with_suffix(".md").write_text(markdown_companion(payload, diagrams), encoding="utf-8")
    templates = ROOT / "templates/presentations/cinimex-consulting"
    reference = workspace / "reference.pptx"
    run_node(templates / "render.mjs", reference, workspace=workspace)
    helpers = skill / "template_following_scripts"
    run_node(
        helpers / "inspect_template_deck.mjs",
        "--workspace",
        workspace,
        "--pptx",
        reference,
        workspace=workspace,
    )
    renderer = templates / "render-reading.mjs"
    renderer_args = (
        "--root",
        ROOT,
        "--workspace",
        workspace,
        "--input",
        payload_path,
        "--out",
        out,
        "--spec",
        spec_path,
        "--diagrams",
        diagrams_path,
    )
    run_node(renderer, *renderer_args, "--plan", workspace=workspace)
    run_node(
        helpers / "prepare_template_starter_deck.mjs",
        "--workspace",
        workspace,
        "--pptx",
        reference,
        "--map",
        workspace / "reading-frame-map.json",
        "--out",
        workspace / "reading-starter.pptx",
        workspace=workspace,
    )
    run_node(renderer, *renderer_args, workspace=workspace)
    extracted = extract_text(out)
    text_path = out.with_suffix(".txt")
    text_path.write_text(
        "\n\n".join(
            f"SLIDE {index}\n{slide['text']}\n\nNOTES\n{slide['notes']}"
            for index, slide in enumerate(extracted, 1)
        )
        + "\n",
        encoding="utf-8",
    )
    check = verify_text(spec, company, diagrams, extracted)
    check["extracted_text"] = str(text_path)
    update_manifest(out.with_suffix(".manifest.json"), check)
    if not check["passed"]:
        raise ValueError("PPTX text verification failed:\n" + "\n".join(check["missing"]))
    return {
        "output": str(out),
        "workspace": str(workspace),
        "slides": len(extracted),
        "preview": str(out.with_name(out.stem + "-preview")),
        "visual_review": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="canonical reading-deck JSON")
    parser.add_argument("--out", type=Path, required=True, help="PPTX path under ignored dist/")
    parser.add_argument(
        "--diagrams", type=Path, help="defaults to sibling diagrams.json, if present"
    )
    parser.add_argument(
        "--presentation-skill", type=Path, help="installed Presentations skill folder"
    )
    args = parser.parse_args(argv)
    try:
        if args.diagrams and not args.diagrams.is_file():
            raise ValueError(f"--diagrams file does not exist: {args.diagrams}")
        result = build(args.spec, args.out, args.diagrams, find_skill(args.presentation_skill))
    except (
        ValueError,
        OSError,
        KeyError,
        ContentError,
        BadZipFile,
        ET.ParseError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Reading deck: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
