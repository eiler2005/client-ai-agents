#!/usr/bin/env python3
"""Search and validate the portable management/visual library; standard library only."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
FORMATS = {"slides", "document"}
VERIFIED_FORMATS = {"slides", "pdf", "docx", "markdown"}


def local_file(root: Path, value: str) -> bool:
    candidate = (root / value).resolve()
    return candidate.is_relative_to(root.resolve()) and candidate.is_file()


def validate(catalog: dict, root: Path) -> list[str]:
    """Check identity, links and maturity without deciding whether a layout is clear."""
    problems = []
    entries = catalog.get("entries", [])
    sources = catalog.get("sources", [])
    if not isinstance(entries, list) or not isinstance(sources, list):
        return ["entries and sources must be lists"]
    if not entries:
        problems.append("entries must not be empty")
    for label, records in (("entry", entries), ("source", sources)):
        if any(
            not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in records
        ):
            return [f"each {label} requires a string id"]
        ids = [item["id"] for item in records]
        if len(ids) != len(set(ids)):
            problems.append(f"duplicate {label} id")
    by_id = {item["id"]: item for item in entries}
    source_ids = {item["id"] for item in sources}
    for source in sources:
        if not local_file(root, source.get("reference", "")):
            problems.append(f"{source['id']}: missing or unsafe source reference")
        if source.get("url") and not source["url"].startswith("https://"):
            problems.append(f"{source['id']}: public source must use https")
    for entry in entries:
        key = entry["id"]
        kind = entry.get("kind")
        if kind not in {"management", "visual"}:
            problems.append(f"{key}: invalid kind")
        expected = "M" if kind == "management" else "V"
        if not re.fullmatch(expected + r"\d{2,}", key):
            problems.append(f"{key}: invalid id for kind")
        for field in ("title", "question"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                problems.append(f"{key}: missing {field}")
        for field in ("tags", "required_inputs", "related", "sources", "formats"):
            values = entry.get(field)
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                problems.append(f"{key}: {field} must be a list of strings")
        if not local_file(root, entry.get("reference", "")):
            problems.append(f"{key}: missing or unsafe recipe reference")
        for related in entry.get("related", []):
            if related not in by_id:
                problems.append(f"{key}: unknown related id {related}")
            elif by_id[related].get("kind") == kind:
                problems.append(f"{key}: related must link management to visual")
        for source in entry.get("sources", []):
            if source not in source_ids:
                problems.append(f"{key}: unknown source {source}")
        if not entry.get("formats") or set(entry.get("formats", [])) - FORMATS:
            problems.append(f"{key}: invalid applicability formats")
        if entry.get("review_status") not in {"candidate", "reviewed"}:
            problems.append(f"{key}: invalid review status")
        maturity = entry.get("implementation_status")
        if maturity not in {"recipe", "example"}:
            problems.append(f"{key}: invalid implementation status")
        scripts = entry.get("example_scripts", {})
        if not isinstance(scripts, dict):
            problems.append(f"{key}: example_scripts must be an object")
            scripts = {}
        if maturity == "example" and not scripts:
            problems.append(f"{key}: executable example requires a script")
        for output_format, script in scripts.items():
            if output_format not in VERIFIED_FORMATS or not local_file(root, script):
                problems.append(f"{key}: missing or unsafe example script for {output_format}")
        verified = entry.get("verified_formats", [])
        if not isinstance(verified, list) or set(verified) - VERIFIED_FORMATS:
            problems.append(f"{key}: invalid verified_formats")
        elif any(output_format not in scripts for output_format in verified):
            problems.append(f"{key}: verified format lacks an example script")
    return problems


def search(catalog: dict, query: str, kind: str | None, output_format: str | None) -> list[dict]:
    """Match ID/Russian/English tags; all words must occur, strongest matches first."""
    words = query.casefold().split()
    found = []
    for entry in catalog["entries"]:
        if kind and entry["kind"] != kind:
            continue
        if output_format and output_format not in entry["formats"]:
            continue
        headline = " ".join([entry["id"], entry["title"], *entry["tags"]]).casefold()
        body = " ".join([headline, entry["question"], *entry["required_inputs"]]).casefold()
        if all(word in body for word in words):
            score = sum(
                3 if word == entry["id"].casefold() else 1 for word in words if word in headline
            )
            found.append((score, entry))
    return [entry for _, entry in sorted(found, key=lambda item: (-item[0], item[1]["id"]))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["list", "search", "check"])
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--kind", choices=["management", "visual"])
    parser.add_argument("--format", dest="output_format", choices=sorted(FORMATS))
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--catalog", type=Path, default=SKILL_DIR / "library" / "catalog.json")
    args = parser.parse_args()
    try:
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        problems = validate(catalog, SKILL_DIR)
        if problems:
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1
    except (OSError, ValueError, TypeError) as exc:
        print(f"Cannot load library: {exc}", file=sys.stderr)
        return 1
    if args.action == "check":
        print(f"OK: {len(catalog['entries'])} templates, {len(catalog['sources'])} sources")
        return 0
    if args.action == "search" and not args.query.strip():
        parser.error("search requires a query")
    if args.limit < 1:
        parser.error("--limit must be positive")
    found = search(catalog, args.query, args.kind, args.output_format)
    if args.action == "search":
        found = found[: args.limit]
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=2))
    else:
        for entry in found:
            print(f"{entry['id']} · {entry['title']} [{entry['implementation_status']}]")
            print(f"  {entry['question']}")
            print(f"  {entry['reference']} · related: {', '.join(entry['related'])}")
        if not found:
            print("No matching template. Adapt a nearby recipe or add a reviewed candidate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
