"""Редактируемые презентации из тех же проверенных данных, что отчёт и КП."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .content import CONTENT, Company, ContentError, Proposal, read_yaml, validate
from .image_quality import inspect_pptx_images
from .render import CONFIDENCE, HORIZON_TITLE
from .scoring import Result

BUILDER = Path(__file__).with_name("presentation.mjs")


def load_style() -> dict:
    style = read_yaml(CONTENT / "presentation.yaml")
    problems = validate(style, "presentation.schema.json", "presentation.yaml")
    if problems:
        raise ContentError(problems)
    return style


def slide(kind: str, title: str, source: str, **content) -> dict:
    return {"kind": kind, "title": title, "source": source, **content}


def table_slides(title: str, source: str, headers: list[str], rows: list[list[str]]) -> list[dict]:
    return [
        slide(
            "table",
            title,
            source,
            headers=headers,
            rows=rows[start : start + 2],
            page=start // 2 + 1,
            pages=(len(rows) + 1) // 2,
        )
        for start in range(0, len(rows), 2)
    ]


def assessment_core(result: Result) -> list[dict]:
    assessment = result.assessment
    source = f"Оценка от {assessment.assessed} · рубрика v{result.rubric.version}"
    decision = result.verdict["name"]
    if assessment.status != "final":
        decision = "Предварительно: " + decision.lower()
    parts = [
        slide(
            "summary",
            decision,
            source,
            metrics=[
                [
                    f"{result.overall:.0f}/100" if result.scored else "—",
                    "Готовность по оценённым измерениям",
                ],
                [f"{result.coverage:.0f}%", "Охват оценки"],
                [str(len(result.blockers)), "Блокирующих пробелов"],
            ],
            points=assessment.highlights[:3] or [assessment.project["summary"]],
            rationale=assessment.verdict_note.get("rationale", ""),
            conditions=assessment.verdict_note.get("conditions", []),
            warnings=result.notes,
        )
    ]
    for start in range(0, len(result.dimensions), 6):
        dimensions = result.dimensions[start : start + 6]
        parts.append(
            slide(
                "score",
                "Карта зрелости показывает, что готово и что требует внимания",
                source + " · уровни 0–4; неоценённое не считается нулём",
                dimensions=[
                    {
                        "id": item.id,
                        "name": item.dimension.get("short", item.name),
                        "level": item.level,
                        "confidence": CONFIDENCE.get(item.confidence, "—"),
                        "blocking": item.blocking,
                        "evidence": item.evidence,
                        "finding": item.finding,
                    }
                    for item in dimensions
                ],
            )
        )
    gaps = sorted(result.gaps, key=lambda item: (item not in result.blockers, -item.gap))[:3]
    if gaps:
        parts += table_slides(
            "Эти пробелы нужно закрывать в первую очередь",
            source + " · " + "; ".join(f"{item.id}: {', '.join(item.evidence)}" for item in gaps),
            ["Измерение", "Наблюдение", "Рекомендация"],
            [[item.name, item.finding, item.recommendation or item.risk] for item in gaps],
        )
    return parts


def closing(company: Company, steps: list[str], source: str) -> dict:
    return slide(
        "closing",
        "Согласуем следующий шаг и ответственных",
        source,
        points=steps,
        contacts=company.contacts_for(),
        organisation=company.organisation["legal_name"],
        site=company.organisation.get("site", ""),
    )


def assessment_deck(result: Result, company: Company) -> dict:
    assessment = result.assessment
    source = f"Оценка от {assessment.assessed} · рубрика v{result.rubric.version}"
    parts = [
        slide(
            "cover",
            assessment.name,
            source,
            subtitle="Оценка проекта ИИ-агента",
            client=assessment.client,
            date=assessment.assessed,
            status=assessment.status,
        ),
        *assessment_core(result),
        slide(
            "text",
            "Оценка охватывает согласованный периметр проекта",
            source,
            points=[
                assessment.project["summary"],
                *assessment.project.get("scope", {}).get("in", []),
            ],
            exclusions=assessment.project.get("scope", {}).get("out", []),
        ),
    ]
    metrics = assessment.project.get("metrics", [])
    if metrics:
        parts += table_slides(
            "Фактические метрики показывают расстояние до цели",
            source,
            ["Метрика", "Факт", "Цель"],
            [[item["name"], item.get("actual", "—"), item.get("target", "—")] for item in metrics],
        )
    risks = result.critical_risks or assessment.risks
    if risks:
        parts += table_slides(
            "До следующего этапа нужно снизить ключевые риски",
            source,
            ["Риск", "Мера", "Владелец и срок"],
            [
                [
                    item["title"],
                    item.get("mitigation", "—"),
                    " · ".join(filter(None, [item.get("owner"), item.get("due")])) or "—",
                ]
                for item in risks[:3]
            ],
        )
    for horizon, actions in result.plan():
        if actions:
            parts += table_slides(
                f"{HORIZON_TITLE[horizon]}: действия с проверяемым результатом",
                source,
                ["Действие", "Результат", "Владелец"],
                [
                    [item["title"], item.get("outcome", "—"), item.get("owner", "—")]
                    for item in actions
                ],
            )
    parts.append(
        closing(
            company,
            assessment.verdict_note.get("conditions", [])
            or [
                "Обсудить выводы оценки с командой проекта",
                "Согласовать план действий, владельцев и условия следующего этапа",
            ],
            source,
        )
    )
    deck = payload(
        assessment.id,
        "assessment",
        assessment.assessed,
        parts,
        [
            assessment.path,
            CONTENT / "rubric.yaml",
            CONTENT / "company.yaml",
        ],
        warnings=result.notes,
    )
    deck["references"] = assessment.sources
    deck["brand"] = company.name.upper()
    return deck


def proposal_deck(offer: Proposal, company: Company, result: Result | None = None) -> dict:
    if offer.assessment_id and (result is None or result.assessment.id != offer.assessment_id):
        raise ContentError([f"{offer.id}: не найдена связанная оценка {offer.assessment_id}"])
    source = f"Предложение от {offer.date} · профиль {company.name} v{company.version}"
    parts = [
        slide(
            "cover",
            offer.name,
            source,
            subtitle="Предложение по развитию проекта",
            client=offer.client_name,
            date=offer.date,
            status=offer.status,
        ),
        slide(
            "summary",
            f"Предлагаем план на {offer.weeks:g} недель",
            source,
            metrics=[
                [f"{offer.weeks:g}", "Недель работ"],
                [str(len(offer.stages)), "Этапов работ"],
            ],
            points=[offer.project["summary"], *offer.context.get("goals", [])],
            rationale=offer.context["problem"],
        ),
    ]
    if result:
        parts += assessment_core(result)
    parts += table_slides(
        "Согласуем объём работ и границы ответственности",
        source,
        ["В объёме", "Вне объёма"],
        [
            [
                "\n".join(offer.scope.get("in", [])[i : i + 2]),
                "\n".join(offer.scope.get("out", [])[i : i + 2]),
            ]
            for i in range(
                0, max(len(offer.scope.get("in", [])), len(offer.scope.get("out", []))), 2
            )
        ],
    )
    parts += table_slides(
        "Каждый этап заканчивается результатом и условием перехода",
        source,
        ["Этап и срок", "Результат", "Условие перехода"],
        [
            [
                f"{item['name']} · {item['weeks']:g} нед.",
                "\n".join(item["deliverables"]),
                item.get("gate", "—"),
            ]
            for item in offer.stages
        ],
    )
    if offer.team:
        parts += table_slides(
            "За каждой зоной работы закреплена роль в команде",
            source,
            ["Роль", "Численность и загрузка", "Ответственность"],
            [
                [
                    item["role"],
                    f"{item['count']:g} · {item.get('load', '—')}",
                    item.get("note", "—"),
                ]
                for item in offer.team
            ],
        )
    if offer.commercials:
        parts.append(
            slide(
                "text",
                "Стоимость и сроки опираются на согласованные допущения",
                source,
                points=[
                    f"Стоимость: {offer.commercials.get('total', 'не указана')}",
                    f"Срок действия предложения: {offer.valid_until or 'не указан'}",
                    *offer.commercials.get("terms", []),
                ],
                assumptions=offer.commercials.get("assumptions", []),
                stages=offer.stages,
            )
        )
    if offer.risks:
        parts += table_slides(
            "Риски учитываем до старта работ",
            source,
            ["Риск", "Мера"],
            [[item["title"], item["mitigation"]] for item in offer.risks],
        )
    facts = [company.by_fact[item] for item in offer.about.get("facts", company.by_fact)]
    proof = (
        [company.by_proof[item] for item in offer.about["proof"]]
        if offer.about.get("proof")
        else company.proof_for(offer.industry, limit=2)
    )
    parts.append(
        slide(
            "text",
            "Синимекс предлагает подтверждённый опыт для этой задачи",
            source,
            points=[
                company.organisation["positioning"],
                *[f"{item['label']}: {item['value']}" for item in facts[:3]],
            ],
            facts=facts,
            proof=proof,
            caveat=company.caveat,
        )
    )
    if proof:
        proof_slides = table_slides(
            "Опыт других проектов даёт опору для обсуждения решения",
            source + " · " + "; ".join(item["source"] for item in proof),
            ["Задача", "Результат"],
            [[item["title"], item["result"]] for item in proof],
        )
        for part in proof_slides:
            part["caveat"] = company.caveat
        parts += proof_slides
    parts.append(
        closing(company, offer.next_steps or ["Обсудить объём и план первого этапа"], source)
    )
    inputs = [offer.path, CONTENT / "company.yaml"]
    if result:
        inputs += [result.assessment.path, CONTENT / "rubric.yaml"]
    deck = payload(
        offer.id,
        "proposal",
        offer.date,
        parts,
        inputs,
        warnings=[
            *(result.notes if result else []),
            *[
                f"Факт «{fact['label']}» датирован {fact['as_of']} — подтвердите"
                for fact in company.stale_facts()
            ],
        ],
    )
    deck["references"] = [*company.sources.values(), *(result.assessment.sources if result else [])]
    deck["brand"] = company.name.upper()
    return deck


def payload(
    identifier: str,
    kind: str,
    date: str,
    parts: list[dict],
    inputs: list[Path],
    *,
    warnings: list[str],
) -> dict:
    return {
        "id": identifier,
        "kind": kind,
        "date": date,
        "style": load_style(),
        "slides": parts,
        "warnings": warnings,
        "inputs": [
            {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in [*inputs, CONTENT / "presentation.yaml", BUILDER, Path(__file__)]
        ],
    }


def build(deck: dict, out: Path) -> dict:
    """Сборка не запускает PDF-рендерер или генератор страниц."""
    if not shutil.which("node"):
        raise ContentError(["Для презентаций нужен Node.js 22 или новее"])
    runtime = Path(
        os.environ.get(
            "CINIMEX_ARTIFACT_TOOL",
            Path.home()
            / ".cache"
            / "codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
            / "@oai/artifact-tool",
        )
    )
    entry = next(
        (
            runtime / item
            for item in ["dist/node/artifact_tool.mjs", "dist/artifact_tool.mjs"]
            if (runtime / item).is_file()
        ),
        None,
    )
    if entry is None:
        raise ContentError(
            [
                "Не найден @oai/artifact-tool. Укажите каталог пакета "
                "в CINIMEX_ARTIFACT_TOOL (см. docs/PRESENTATION.md)"
            ]
        )
    metadata = json.loads((runtime / "package.json").read_text(encoding="utf-8"))
    if metadata.get("name") != "@oai/artifact-tool":
        raise ContentError(["CINIMEX_ARTIFACT_TOOL должен указывать на пакет @oai/artifact-tool"])
    deck = {**deck, "renderer": {"name": metadata["name"], "version": metadata["version"]}}
    workspace = Path(tempfile.mkdtemp(prefix="cinimex-slides-"))
    source = workspace / "presentation.mjs"
    shutil.copy2(BUILDER, source)
    input_path = workspace / "deck.json"
    input_path.write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{deck['id']}-{deck['kind']}-{deck['date']}.pptx"
    process = subprocess.run(
        ["node", str(source), str(input_path), str(target), str(entry)],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode:
        raise ContentError(
            ["Презентация не собрана: " + (process.stderr or process.stdout)[-2500:]]
        )
    manifest = json.loads(target.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    image_quality = inspect_pptx_images(target)
    manifest.setdefault("checks", {})["image_quality"] = image_quality
    target.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not image_quality["passed"]:
        raise ContentError(["Качество изображений: " + error for error in image_quality["errors"]])
    return {**manifest, "workspace": str(workspace)}
