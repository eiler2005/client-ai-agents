"""Текст отчёта в Markdown. Один источник разделов для страницы в docs и для PDF.

Разделы собираются один раз и отдаются обоим потребителям: сайт печатает их как H2 на
одной странице, PDF — как части с H1 и разрывом страницы между ними. Поэтому раздел
возвращает заголовок и строки отдельно, а уровень вложенных подзаголовков считается от
переданной глубины. Фигуры подставляет вызывающая сторона: в docs это `<picture>` со
светлым и тёмным SVG, в PDF — растрированный PNG, который понимает принтер.

Разметка ограничена тем, что умеет рендерер PDF: заголовки, абзацы, выделение, списки,
таблицы, ссылки http(s) и картинка. Ничего другого сюда писать нельзя — иначе страница
в docs и книга разойдутся.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .content import Assessment, Company, Rubric, load_company
from .scoring import Result, portfolio, risk_weight

GENERATED = (
    "<!-- Этот файл собирается командой `assess build`. Правьте источники в "
    "src/content/ и assessments/, а не его. -->"
)
BANNER = "Файл собран из рубрики и файлов оценки. Правки вручную будут потеряны."
LEVEL_MARK = {0: "0", 1: "1", 2: "2", 3: "3", 4: "4"}
CONFIDENCE = {"high": "высокая", "medium": "средняя", "low": "низкая"}
EFFORT = {"s": "малое", "m": "среднее", "l": "большое"}
IMPACT = {"high": "высокое", "medium": "среднее", "low": "низкое"}
SOURCE_KIND = {
    "interview": "интервью",
    "demo": "демонстрация",
    "document": "документ",
    "code": "код",
    "telemetry": "телеметрия",
    "test": "прогон тестов",
    "observation": "наблюдение",
}
HORIZON_TITLE = {30: "Первые 30 дней", 60: "31–60 дней", 90: "61–90 дней"}


def heading(level: int, text: str) -> str:
    return f"{'#' * level} {text}"


def label_short(rubric: Rubric, dimension: str) -> str:
    """Короткое имя измерения — для узких колонок таблиц."""
    item = rubric.by_id[dimension]
    return item.get("short") or item["name"]


def contact_card(company: Company, chosen: list[str] | None = None, *, depth: int = 2) -> list[str]:
    """Карточка контактов в конце документа, уходящего клиенту.

    Один и тот же блок печатается в отчёте об оценке, в коммерческом предложении и в
    любом другом документе: адресат не должен искать, кому писать, в сопроводительном
    письме, которое к документу уже не приложено.
    """
    people = company.contacts_for(chosen)
    if not people:
        return []
    organisation = company.organisation
    lines = [
        "По вопросам к документу обращайтесь:",
        "",
    ]
    for person in people:
        lines += [heading(depth, person["name"]), ""]
        position = person["role"]
        if person.get("unit"):
            position += f", {person['unit']}"
        lines += [f"*{position}*", ""]
        channels = []
        if person.get("phone"):
            channels.append(["Телефон", person["phone"]])
        if person.get("telegram"):
            channels.append(["Telegram", f"@{person['telegram']}"])
        if person.get("email"):
            channels.append(["Почта", person["email"]])
        lines += table(["Канал", "Контакт"], channels)
        lines += [""]
    lines += [
        f"{organisation['legal_name']}"
        + (f" · {organisation['site']}" if organisation.get("site") else "")
    ]
    return lines


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    return [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
        *["| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |" for row in rows],
    ]


def picture(assets: str, name: str, caption: str) -> list[str]:
    """Пара фигур под светлую и тёмную тему; PDF возьмёт светлую."""
    return [
        "<picture>",
        f'<source srcset="{assets}/{name}.dark.svg" media="(prefers-color-scheme: dark)">',
        f'<img src="{assets}/{name}.svg" alt="{caption}">',
        "</picture>",
        "",
        f"*{caption}*",
    ]


def plain_image(name: str, caption: str) -> list[str]:
    """Для PDF: подпись у фигуры уже нарисована внутри неё, второй раз не нужна."""
    return [f"![]({name}.png)"]


class Sections:
    """Разделы отчёта по одной оценке. `figure` решает, как вставлять фигуру."""

    def __init__(
        self,
        result: Result,
        depth: int,
        figure: Callable[[str, str], list[str]],
        *,
        detail: bool = True,
    ):
        self.result = result
        self.assessment: Assessment = result.assessment
        self.rubric: Rubric = result.rubric
        self.company = load_company()
        self.depth = depth
        self.figure = figure
        # Краткая версия отчёта оставляет карту оценки, но не разбор каждого измерения.
        self.detail = detail

    def sub(self, text: str) -> str:
        return heading(self.depth + 1, text)

    def subsub(self, text: str) -> str:
        return heading(self.depth + 2, text)

    def parts(self) -> list[tuple[str, list[str]]]:
        return [
            ("Резюме для руководства", self.summary()),
            ("Контекст и периметр", self.context()),
            ("Оценка по измерениям", self.scorecard()),
            *([("Риски", self.risks())] if self.assessment.risks else []),
            *([("План 30/60/90", self.plan())] if self.assessment.actions else []),
            ("Методология и шкала", self.methodology()),
            *([("Источники оценки", self.sources())] if self.assessment.sources else []),
            *(
                [("Контакты", contact_card(self.company, depth=self.depth + 1))]
                if self.company.contacts
                else []
            ),
        ]

    # --- Резюме ---------------------------------------------------------------

    def summary(self) -> list[str]:
        result = self.result
        project = self.assessment.project
        stage = self.rubric.stages.get(project["stage"], {}).get("name", project["stage"])
        pattern = self.rubric.patterns.get(project["pattern"], {}).get("name", project["pattern"])
        lines = [
            f"**Решение: {result.verdict['name']}.** {result.verdict['description']}",
            "",
            f"Взвешенная готовность — **{result.overall:.0f} из 100** при охвате "
            f"{result.coverage:.0f} % измерений рубрики.",
            "",
        ]
        if self.assessment.status != "final":
            lines += [
                "*Это предварительная оценка: часть измерений ещё не разобрана, и решение "
                "по проекту может измениться, когда охват дойдёт до полного.*",
                "",
            ]
        if note := self.assessment.verdict_note.get("rationale"):
            lines += [note, ""]
        lines += table(
            ["Параметр", "Значение"],
            [
                ["Проект", self.assessment.name],
                ["Заказчик", self.assessment.client],
                ["Стадия", stage],
                ["Тип решения", pattern],
                ["Готовность", f"{result.overall:.0f} из 100"],
                ["Охват оценки", f"{len(result.scored)} из {len(result.dimensions)} измерений"],
                ["Решение", result.verdict["name"]],
                ["Дата оценки", self.assessment.assessed],
                [
                    "Статус отчёта",
                    {"draft": "черновик", "review": "на ревью", "final": "итоговый"}[
                        self.assessment.status
                    ],
                ],
            ],
        )
        if self.assessment.highlights:
            lines += ["", self.sub("Ключевые выводы")]
            lines += [
                f"{index}. {text}" for index, text in enumerate(self.assessment.highlights, 1)
            ]
        if conditions := self.assessment.verdict_note.get("conditions"):
            lines += ["", self.sub("Условия перехода к следующему шагу")]
            lines += [f"- {text}" for text in conditions]
        if result.blockers:
            names = ", ".join(item.name for item in result.blockers)
            lines += [
                "",
                self.sub("Блокирующие пробелы"),
                f"Измерения {names} находятся на уровне 0–1. Это блокирующие измерения "
                f"рубрики: пока они на этом уровне, решение по проекту не поднимается выше "
                f"«{self.rubric.verdict('fix')['name']}» независимо от средней оценки.",
            ]
        strengths = result.strengths[:3]
        gaps = result.gaps[:3]
        if strengths or gaps:
            lines += ["", self.sub("На что опереться и что закрывать")]
        if strengths:
            lines += ["", "**Опора:**"]
            lines += [
                f"- {item.name} — уровень {item.level}. {item.strength or item.finding}"
                for item in strengths
            ]
        if gaps:
            lines += ["", "**Закрывать первым:**"]
            lines += [
                f"- {item.name} — уровень {item.level}. "
                f"{item.recommendation or item.risk or item.finding}"
                for item in gaps
            ]
        return lines

    # --- Контекст -------------------------------------------------------------

    def context(self) -> list[str]:
        project = self.assessment.project
        lines = [project["summary"], ""]
        if sponsor := project.get("sponsor"):
            lines += [f"**Заказчик процесса:** {sponsor}", ""]
        scope = project.get("scope", {})
        if scope.get("in"):
            lines += [self.sub("В периметре оценки")]
            lines += [f"- {text}" for text in scope["in"]]
            lines += [""]
        if scope.get("out"):
            lines += [self.sub("Вне периметра")]
            lines += [f"- {text}" for text in scope["out"]]
            lines += [""]
        if project.get("metrics"):
            lines += [self.sub("Метрики проекта")]
            lines += table(
                ["Метрика", "База", "Цель", "Факт", "Примечание"],
                [
                    [
                        metric["name"],
                        metric.get("baseline", "—"),
                        metric.get("target", "—"),
                        metric.get("actual", "—"),
                        metric.get("note", ""),
                    ]
                    for metric in project["metrics"]
                ],
            )
            lines += [""]
        if project.get("stack"):
            lines += [self.sub("Технологический контур")]
            lines += table(
                ["Слой", "Что используется"],
                [[layer, ", ".join(items)] for layer, items in project["stack"].items()],
            )
            lines += [""]
        who = ", ".join(project.get("assessors", [])) or "—"
        kinds: dict[str, int] = {}
        for source in self.assessment.sources:
            kinds[source["kind"]] = kinds.get(source["kind"], 0) + 1
        basis = ", ".join(
            f"{SOURCE_KIND.get(kind, kind)} — {count}" for kind, count in sorted(kinds.items())
        )
        lines += [
            self.sub("Как собиралась оценка"),
            f"Оценку проводили: {who}. Дата оценки — {self.assessment.assessed}. "
            f"Основание: {basis or 'источники не зафиксированы'}.",
            "",
            "Уверенность указана по каждому измерению отдельно: «высокая» означает, что мы "
            "видели артефакт или прогон своими глазами, «низкая» — что вывод держится на "
            "одном непроверенном источнике и требует подтверждения.",
        ]
        return lines

    # --- Измерения ------------------------------------------------------------

    def scorecard(self) -> list[str]:
        result = self.result
        lines = self.figure(f"scorecard.{self.assessment.id}", "Карта оценки по измерениям")
        lines += [""]
        lines += table(
            ["Измерение", "Группа", "Вес", "Уровень", "Уверенность"],
            [
                [
                    item.name + (" (блокирующее)" if item.blocking else ""),
                    self.rubric.groups_by_id[item.group]["name"],
                    f"{item.weight:g}",
                    (
                        f"{item.level} — {self.rubric.level_name(item.level or 0)}"
                        if item.scored
                        else "не оценено"
                    ),
                    CONFIDENCE.get(item.confidence or "", "—"),
                ]
                for item in result.dimensions
            ],
        )
        lines += [""]
        lines += self.figure(f"radar.{self.assessment.id}", "Уровни зрелости по измерениям")
        if not self.detail:
            return lines
        for group in self.rubric.groups:
            inside = [
                item for item in result.dimensions if item.group == group["id"] and item.scored
            ]
            if not inside:
                continue
            score = next(item for item in result.groups if item.group["id"] == group["id"])
            lines += [
                "",
                self.sub(f"{group['name']}: {score.score:.0f} из 100"),
                f"*{group['question']}*",
            ]
            for item in inside:
                lines += ["", self.subsub(f"{item.name} — уровень {item.level}")]
                mark = self.rubric.level_name(item.level or 0)
                confidence = CONFIDENCE.get(item.confidence or "", "не указана")
                lines += [
                    f"**Уровень:** {item.level} — {mark}. **Уверенность:** {confidence}. "
                    f"**Вес:** {item.weight:g}.",
                    "",
                    f"**Наблюдение:** {item.finding}",
                ]
                if item.strength:
                    lines += ["", f"**Что работает:** {item.strength}"]
                if item.risk:
                    lines += ["", f"**Чем это грозит:** {item.risk}"]
                if item.recommendation:
                    lines += ["", f"**Рекомендация:** {item.recommendation}"]
                if item.criteria:
                    # Порядок — как в рубрике: критерии идут от замысла к проверке,
                    # и алфавит этот порядок ломает.
                    detail = "; ".join(
                        f"{criterion['name']} — {item.criteria[criterion['id']]}"
                        for criterion in item.dimension["criteria"]
                        if criterion["id"] in item.criteria
                    )
                    lines += ["", f"**По критериям:** {detail}."]
                if item.evidence:
                    refs = []
                    for source_id in item.evidence:
                        source = self.assessment.source(source_id)
                        refs.append(
                            f"{source_id} ({SOURCE_KIND.get(source['kind'], source['kind'])}, "
                            f"{source['date']})"
                            if source
                            else source_id
                        )
                    lines += ["", f"**Основание:** {', '.join(refs)}."]
        return lines

    # --- Риски ----------------------------------------------------------------

    def risks(self) -> list[str]:
        risks = sorted(self.assessment.risks, key=lambda item: -risk_weight(item))
        lines = self.figure(f"risks.{self.assessment.id}", "Карта рисков: вероятность и влияние")
        lines += [""]
        lines += table(
            ["ID", "Риск", "Вероятность и влияние", "Мера", "Владелец и срок"],
            [
                [
                    risk["id"],
                    risk["title"],
                    f"{IMPACT[risk['probability']]} / {IMPACT[risk['impact']]}",
                    risk.get("mitigation", "—"),
                    ", ".join(part for part in (risk.get("owner"), risk.get("due")) if part) or "—",
                ]
                for risk in risks
            ],
        )
        critical = self.result.critical_risks
        if critical:
            lines += [
                "",
                f"**Требуют решения до следующего шага:** "
                f"{', '.join(risk['id'] for risk in critical)}.",
            ]
        return lines

    # --- План -----------------------------------------------------------------

    def plan(self) -> list[str]:
        lines = [
            "Порядок внутри горизонта — по отдаче на усилие. Горизонт указывает, когда "
            "действие должно быть завершено, а не когда начато.",
        ]
        for horizon, actions in self.result.plan():
            if not actions:
                continue
            lines += ["", self.sub(HORIZON_TITLE[horizon])]
            lines += table(
                ["Действие", "Проверяемый результат", "Измерение", "Усилие / отдача", "Владелец"],
                [
                    [
                        f"**{action['id']}.** {action['title']}",
                        action.get("outcome", "—"),
                        (
                            label_short(self.rubric, action["dimension"])
                            if action.get("dimension")
                            else "—"
                        ),
                        f"{EFFORT.get(action.get('effort', ''), '—')} / "
                        f"{IMPACT.get(action.get('impact', ''), '—')}",
                        action.get("owner", "—"),
                    ]
                    for action in actions
                ],
            )
        return lines

    # --- Методология ----------------------------------------------------------

    def methodology(self) -> list[str]:
        rubric = self.rubric
        blocking = [item["name"] for item in rubric.dimensions if item.get("blocking")]
        lines = [
            f"Оценка сделана по рубрике версии {rubric.version} от {rubric.updated}: "
            f"{len(rubric.dimensions)} измерений в {len(rubric.groups)} группах, у каждого "
            f"измерения свой вес.",
            "",
            self.sub("Шкала уровней"),
        ]
        lines += table(
            ["Уровень", "Название", "Что это значит"],
            [
                [str(item["level"]), item["name"], item["description"]]
                for item in sorted(rubric.scale, key=lambda item: item["level"])
            ],
        )
        lines += [
            "",
            self.sub("Как считается балл и решение"),
            f"Уровень измерения переводится в проценты (уровень / {rubric.max_level}), "
            f"проценты складываются с весами измерений. В расчёт входят только оцененные "
            f"измерения: неоцененное измерение не считается нулём, но снижает охват.",
            "",
        ]
        lines += table(
            ["Решение", "Порог балла", "Что означает"],
            [
                [item["name"], f"{item['min_score']:g}", item["description"]]
                for item in rubric.verdicts
            ],
        )
        lines += [
            "",
            f"**Блокирующие измерения:** {', '.join(blocking)}. Уровень 0–1 по любому из них "
            f"опускает решение до «{rubric.verdict('fix')['name']}» независимо от балла: эти "
            f"пробелы дороже закрывать после запуска, чем до него.",
            "",
            self.sub("Границы применимости"),
            "Оценка — срез на дату её проведения, а не аудит и не гарантия. Она опирается на "
            "то, что команда проекта показала и рассказала; уверенность по каждому измерению "
            "указана отдельно. Уровень описывает зрелость практики, а не качество работы людей.",
        ]
        return lines

    # --- Источники ------------------------------------------------------------

    def sources(self) -> list[str]:
        lines = [
            "Чем подтверждены выводы. Содержание источников не пересказывается: это перечень "
            "того, что мы смотрели, с датой.",
            "",
        ]
        lines += table(
            ["ID", "Вид", "Источник", "Дата", "Уверенность"],
            [
                [
                    source["id"],
                    SOURCE_KIND.get(source["kind"], source["kind"]),
                    source["title"],
                    source["date"],
                    CONFIDENCE.get(source.get("confidence", ""), "—"),
                ]
                for source in self.assessment.sources
            ],
        )
        return lines


# --- Страницы для docs ---------------------------------------------------------


def report_page(result: Result, assets: str = "../assets") -> str:
    sections = Sections(
        result, depth=2, figure=lambda name, caption: picture(assets, name, caption)
    )
    lines = [
        GENERATED,
        "",
        heading(1, f"{result.assessment.name} — оценка проекта"),
        "",
        f"*{BANNER}*",
        "",
        f"{result.assessment.client} · {result.assessment.assessed} · "
        f"решение: **{result.verdict['name']}** · готовность {result.overall:.0f} из 100",
    ]
    for title, body in sections.parts():
        lines += ["", heading(2, title), "", *body]
    if result.notes:
        lines += ["", heading(2, "Замечания сборки"), ""]
        lines += [f"- {note}" for note in result.notes]
    return "\n".join(lines) + "\n"


def rubric_page(rubric: Rubric) -> str:
    lines = [
        GENERATED,
        "",
        heading(1, "Рубрика оценки проектов ИИ-агентов"),
        "",
        f"*{BANNER}*",
        "",
        f"Версия {rubric.version} от {rubric.updated}. {len(rubric.dimensions)} измерений, "
        f"сумма весов {rubric.weight_total:g}.",
        "",
        heading(2, "Шкала уровней"),
        "",
    ]
    lines += table(
        ["Уровень", "Название", "Что это значит"],
        [
            [str(item["level"]), item["name"], item["description"]]
            for item in sorted(rubric.scale, key=lambda item: item["level"])
        ],
    )
    lines += ["", heading(2, "Решения"), ""]
    lines += table(
        ["Решение", "Порог", "Что означает"],
        [[item["name"], f"{item['min_score']:g}", item["description"]] for item in rubric.verdicts],
    )
    for catalogue, title in ((rubric.stages, "Стадии проекта"), (rubric.patterns, "Типы решений")):
        if catalogue:
            lines += ["", heading(2, title), ""]
            lines += table(
                ["Код", "Название", "Описание"],
                [[item["id"], item["name"], item["description"]] for item in catalogue.values()],
            )
    for group in rubric.groups:
        lines += ["", heading(2, f"{group['name']} — {group['question']}"), ""]
        for dimension in rubric.in_group(group["id"]):
            mark = " · блокирующее" if dimension.get("blocking") else ""
            lines += [
                heading(3, f"{dimension['name']} (вес {dimension['weight']:g}{mark})"),
                "",
                f"*{dimension['question']}*",
                "",
            ]
            lines += table(
                ["Критерий", "Что спрашиваем", "Что считаем подтверждением"],
                [[item["name"], item["probe"], item["evidence"]] for item in dimension["criteria"]],
            )
            lines += ["", "**Опорные описания уровней:**"]
            lines += [
                f"- **{level} — {rubric.level_name(int(level))}:** {text}"
                for level, text in sorted(dimension["anchors"].items())
            ]
            lines += [""]
    return "\n".join(lines) + "\n"


def portfolio_page(results: list[Result], rubric: Rubric, assets: str = "assets") -> str:
    rows = portfolio(results)
    lines = [
        GENERATED,
        "",
        heading(1, "Портфель оценок"),
        "",
        f"*{BANNER}*",
        "",
        f"Оценок в портфеле: {len(rows)}. Рубрика версии {rubric.version} от {rubric.updated}.",
        "",
    ]
    if len(results) > 1:
        lines += picture(assets, "portfolio", "Портфель: готовность против ценности")
        lines += [""]
    lines += table(
        [
            "Код",
            "Проект",
            "Заказчик",
            "Стадия",
            "Готовность",
            "Охват",
            "Решение",
            "Блокеры",
            "Оценено",
        ],
        [
            [
                row["code"],
                row["name"],
                row["client"],
                rubric.stages.get(row["stage"], {}).get("name", row["stage"]),
                f"{row['overall']:.0f}",
                f"{row['coverage']:.0f} %",
                row["verdict"]["name"],
                ", ".join(row["blockers"]) or "—",
                row["assessed"],
            ]
            for row in rows
        ],
    )
    lines += [
        "",
        heading(2, "Что повторяется"),
        "",
    ]
    repeated = recurring_gaps(results)
    if repeated:
        lines += table(
            ["Измерение", "Проектов с уровнем 0–2", "Средний уровень"],
            [[name, str(count), f"{mean:.1f}"] for name, count, mean in repeated],
        )
        lines += [
            "",
            "Измерение, которое проваливается у половины портфеля, — это не проблема "
            "отдельного проекта, а пробел в том, как мы такие проекты ставим.",
        ]
    else:
        lines += ["Повторяющихся пробелов пока не видно: в портфеле слишком мало оценок."]
    lines += ["", heading(2, "Отчёты по проектам"), ""]
    lines += [
        f"- [{result.assessment.name}](reports/{result.assessment.id}.md) — "
        f"{result.assessment.client}, {result.verdict['name']}"
        for result in results
    ]
    return "\n".join(lines) + "\n"


def recurring_gaps(results: list[Result], limit: int = 6) -> list[tuple[str, int, float]]:
    """Измерения, которые чаще всего слабы по всему портфелю."""
    rows: list[tuple[str, int, float]] = []
    for dimension in results[0].rubric.dimensions if results else []:
        levels = [
            item.level
            for result in results
            if (item := result.by_id(dimension["id"])) and item.scored
        ]
        if not levels:
            continue
        weak = sum(1 for level in levels if (level or 0) <= 2)
        if weak:
            rows.append((dimension["name"], weak, sum(levels) / len(levels)))  # type: ignore[arg-type]
    return sorted(rows, key=lambda row: (-row[1], row[2]))[:limit]


def company_page(company) -> str:
    """Профиль компании как страница: всё, что можно сказать клиенту, с источниками."""
    organisation = company.organisation
    lines = [
        GENERATED,
        "",
        heading(1, f"{organisation['name']}: факты для коммерческих документов"),
        "",
        f"*{BANNER}*",
        "",
        f"Профиль версии {company.version} от {company.updated}. "
        f"{organisation['legal_name']}, на рынке с {organisation['founded']} года.",
        "",
        organisation["positioning"],
        "",
        heading(2, "Цифры"),
        "",
    ]
    lines += table(
        ["Показатель", "Значение", "Верно на", "Источник"],
        [[fact["label"], fact["value"], fact["as_of"], fact["source"]] for fact in company.facts],
    )
    stale = company.stale_facts()
    if stale:
        names = ", ".join(fact["label"].lower() for fact in stale)
        lines += [
            "",
            f"**Требуют подтверждения перед отправкой клиенту:** {names}.",
        ]
    lines += ["", heading(2, "Услуги"), ""]
    for offering in company.offerings:
        lines += [heading(3, offering["name"]), "", offering["summary"], ""]
        lines += [f"- {item}" for item in offering.get("includes", [])]
        lines += [""]
    if company.platform:
        lines += [heading(2, company.platform["name"]), "", company.platform["summary"], ""]
        lines += table(
            ["Слой", "Состав"],
            [[layer["name"], "; ".join(layer["items"])] for layer in company.platform["layers"]],
        )
    if company.scenarios:
        lines += ["", heading(2, "Сценарии применения"), ""]
        lines += table(
            ["Сценарий", "Что делает агент", "Заявленный эффект"],
            [
                [item["name"], item["description"], item.get("effect", "—")]
                for item in company.scenarios
            ],
        )
    if company.proof:
        lines += ["", heading(2, "Подтверждённый опыт"), ""]
        lines += table(
            ["Задача", "Результат", "Отрасли", "Верно на", "Источник"],
            [
                [
                    item["title"],
                    item["result"],
                    ", ".join(
                        company.industries.get(key, {}).get("name", key)
                        for key in item.get("industries", [])
                    )
                    or "—",
                    item["as_of"],
                    item["source"],
                ]
                for item in company.proof
            ],
        )
        lines += ["", f"*{company.caveat}*"]
    if company.industries:
        lines += ["", heading(2, "Отрасли"), ""]
        lines += table(
            ["Отрасль", "Что закрываем"],
            [[item["name"], item["description"]] for item in company.industries.values()],
        )
    if company.method:
        lines += ["", heading(2, "Методика выбора сценария"), ""]
        lines += table(
            ["Шаг", "Содержание"],
            [[item["step"], item["description"]] for item in company.method],
        )
    if company.stack:
        lines += ["", heading(2, "Технологический стек"), ""]
        lines += table(
            ["Слой", "Инструменты"],
            [[layer, ", ".join(items)] for layer, items in company.stack.items()],
        )
    lines += ["", heading(2, "Источники"), ""]
    lines += table(
        ["ID", "Источник", "Дата", "Ссылка"],
        [
            [item["id"], item["title"], item["date"], item.get("url", "—")]
            for item in company.sources.values()
        ],
    )
    return "\n".join(lines) + "\n"


def proposal_page(proposal, company, assessment: Result | None = None) -> str:
    """Коммерческое предложение как страница для внутренней вычитки."""
    from .proposal import ProposalSections

    sections = ProposalSections(
        proposal,
        company,
        depth=2,
        figure=lambda name, caption: picture("../assets", name, caption),
        assessment=assessment,
    )
    lines = [
        GENERATED,
        "",
        heading(1, f"{proposal.name} — коммерческое предложение"),
        "",
        f"*{BANNER}*",
        "",
        f"{proposal.client_name} · {proposal.date} · {proposal.weeks:g} недель · "
        f"статус: {proposal.status}",
    ]
    for title, body in sections.parts():
        lines += ["", heading(2, title), "", *body]
    return "\n".join(lines) + "\n"


def write_proposal_docs(docs: Path, proposals: list, company, linked: dict) -> list[Path]:
    written = [docs / "COMPANY.md"]
    (docs / "COMPANY.md").write_text(company_page(company), encoding="utf-8")
    target = docs / "proposals"
    target.mkdir(parents=True, exist_ok=True)
    for proposal in proposals:
        path = target / f"{proposal.id}.md"
        page = proposal_page(proposal, company, linked.get(proposal.assessment_id or ""))
        path.write_text(page, encoding="utf-8")
        written.append(path)
    return written


def write_docs(docs: Path, results: list[Result], rubric: Rubric) -> list[Path]:
    written = [docs / "RUBRIC.md"]
    (docs / "RUBRIC.md").write_text(rubric_page(rubric), encoding="utf-8")
    reports = docs / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    for result in results:
        path = reports / f"{result.assessment.id}.md"
        path.write_text(report_page(result), encoding="utf-8")
        written.append(path)
    if results:
        (docs / "PORTFOLIO.md").write_text(portfolio_page(results, rubric), encoding="utf-8")
        written.append(docs / "PORTFOLIO.md")
    return written
