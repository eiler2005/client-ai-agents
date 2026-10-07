"""Презентация, написанная руками: концепция, ТЗ, разбор на встрече.

Отчёт и КП выводятся из проверенных YAML, и слайды для них собираются сами. Но
клиентская работа начинается раньше: на первую встречу едешь с концепцией, которой
ещё нет ни в одной оценке. Этот модуль даёт тот же конвейер и тот же стиль для
материала, который аналитик пишет руками, — чтобы такие слайды не делались каждый
раз заново в постороннем редакторе.

Правила те же, что у остальных документов. Заголовок слайда — утверждение, а не тема:
прочитанные подряд, заголовки должны складываться в довод. Контакты берутся из профиля
компании, а не печатаются в файле. Таблица длиннее двух строк разбивается на слайды
с нумерацией «часть N из M» — это ограничение вёрстки, а не предпочтение.
"""

from __future__ import annotations

from pathlib import Path

from .content import CONTENT, SCHEMA, Company, ContentError, read_yaml, validate
from .slides import payload, slide

ROWS_PER_SLIDE = 2


def expand(part: dict, default_source: str) -> list[dict]:
    """Один слайд описания — один или несколько слайдов презентации."""
    kind = part["kind"]
    source = part.get("source", default_source)
    title = part["title"]
    content = {
        key: value
        for key, value in part.items()
        if key not in {"kind", "title", "source", "rows", "headers"}
    }
    if kind != "table":
        return [slide("points" if kind == "points" else kind, title, source, **content)]

    rows = part["rows"]
    pages = (len(rows) + ROWS_PER_SLIDE - 1) // ROWS_PER_SLIDE
    return [
        slide(
            "table",
            title,
            source,
            headers=part["headers"],
            rows=rows[start : start + ROWS_PER_SLIDE],
            page=start // ROWS_PER_SLIDE + 1,
            pages=pages,
            **content,
        )
        for start in range(0, len(rows), ROWS_PER_SLIDE)
    ]


def load(path: Path, company: Company) -> dict:
    """Читает описание презентации и возвращает колоду для сборщика."""
    data = read_yaml(path)
    problems = validate(data, "deck.schema.json", path.name)
    if not problems:
        problems += _links(data, path)
        for contact in data.get("contacts", []):
            if contact not in company.by_contact:
                problems.append(f"{path.name}: неизвестный контакт профиля «{contact}»")
    if problems:
        raise ContentError(problems)

    default_source = data.get("source") or f"{data['client']} · {data['date']}"
    parts: list[dict] = []
    for part in data["slides"]:
        parts += expand(part, default_source)

    organisation = company.organisation
    for part in parts:
        if part["kind"] == "cover":
            part.setdefault("subtitle", "")
            part["client"] = data["client"]
            part["date"] = data["date"]
            part["status"] = data["status"]
        elif part["kind"] == "closing":
            part["contacts"] = company.contacts_for(data.get("contacts"))
            part["organisation"] = organisation["legal_name"]
            part["site"] = organisation.get("site", "")

    warnings = list(data.get("warnings", []))
    if data["status"] != "final":
        warnings.append("Черновик: выводы и состав работ могут измениться.")
    warnings += [
        f"Факт профиля «{fact['label']}» верен на {fact['as_of']} — подтвердите"
        for fact in company.stale_facts()
    ]
    result = payload(
        data["id"],
        data["kind"],
        data["date"],
        parts,
        [path, CONTENT / "company.yaml", SCHEMA / "deck.schema.json", Path(__file__)],
        warnings=warnings,
    )
    result["brand"] = f"{organisation['name']} · {data['client']}"
    result["references"] = list(company.sources.values())
    return result


def _links(data: dict, path: Path) -> list[str]:
    problems: list[str] = []
    if data["id"] != path.stem and path.stem != "deck":
        problems.append(f"{path.name}: id «{data['id']}» не совпадает с именем файла")
    kinds = [part["kind"] for part in data["slides"]]
    if kinds[0] != "cover":
        problems.append(f"{path.name}: первый слайд должен быть обложкой")
    if kinds.count("cover") > 1:
        problems.append(f"{path.name}: обложка должна быть одна")
    for index, part in enumerate(data["slides"], 1):
        kind = part["kind"]
        if kind == "table" and not (part.get("headers") and part.get("rows")):
            problems.append(f"{path.name}: слайд {index}: таблице нужны headers и rows")
        if kind == "table":
            width = len(part.get("headers", []))
            for row in part.get("rows", []):
                if len(row) != width:
                    problems.append(
                        f"{path.name}: слайд {index}: строка таблицы не совпадает с шапкой"
                    )
                    break
        if kind == "summary" and not part.get("metrics"):
            problems.append(f"{path.name}: слайд {index}: сводке нужны metrics")
        if kind in {"points", "closing"} and not part.get("points"):
            problems.append(f"{path.name}: слайд {index}: нужны points")
        if kind == "cover" and not part.get("subtitle"):
            problems.append(f"{path.name}: слайд {index}: обложке нужен subtitle")
        if kind != "cover" and part["title"].endswith((".", "!")):
            problems.append(
                f"{path.name}: слайд {index}: заголовок — утверждение без точки в конце"
            )
    if data["status"] == "final" and kinds[-1] != "closing":
        problems.append(f"{path.name}: итоговая презентация заканчивается слайдом closing")
    return problems
