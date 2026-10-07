"""Фигуры SVG по тем же проверенным данным, что и текст отчёта.

Два ограничения определяют, как они нарисованы.

Элемента `<style>` здесь нет: таблица стилей умеет тянуть `@import` и `url()`, а фигура
уезжает клиенту. Поэтому каждый цвет стоит на элементе презентационным атрибутом, CSS
нигде нет, и файл можно прочитать глазами целиком.

Тёмная тема решается уровнем выше. Каждая фигура рисуется дважды — под светлую
поверхность и под тёмную, — и Markdown оборачивает пару в `<picture>`. Тёмный вариант
подобран под тёмный фон, а не инвертирован из светлого. Рендерер, который `<picture>`
не понимает (растеризация для PDF), берёт светлый файл и получает корректную фигуру.

Цвет нигде не несёт смысл в одиночку: у каждой точки, полосы и ячейки есть подпись,
а неоцененное измерение помечено формой, а не оттенком.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from xml.sax.saxutils import escape

from .content import RANKS, Proposal, Rubric
from .scoring import Result

FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

# роль → (значение для светлой поверхности, для тёмной). Тёмная колонка подобрана
# под тёмный фон, это не инверсия светлой.
PALETTE: dict[str, tuple[str, str]] = {
    "surface": ("#ffffff", "#17222b"),
    "ink": ("#18364b", "#f2f6f8"),
    "ink2": ("#44596b", "#c3d2dc"),
    "muted": ("#617180", "#8fa3b1"),
    "grid": ("#dde7ec", "#2a3a46"),
    "axis": ("#b9c9d3", "#3c4f5d"),
    "card": ("#f7fafb", "#1d2a34"),
    "accent": ("#137c80", "#2aa5a9"),
    "accentfill": ("rgba(19,124,128,0.18)", "rgba(42,165,169,0.28)"),
    "good": ("#1b7f3b", "#35a95b"),
    "warning": ("#b57c0a", "#e0a829"),
    "critical": ("#b3321f", "#e05a40"),
    "oncell": ("#ffffff", "#0f1a21"),
}
# Один тон для величины: на светлой поверхности «больше» — темнее, на тёмной — светлее.
RAMP = (
    ("#e3edf1", "#22323d"),
    ("#bcd8dc", "#2f5c62"),
    ("#86bcc1", "#3f8188"),
    ("#3f9a9e", "#5fb8bc"),
    ("#137c80", "#9ad7d9"),
)
# С этого шага заливка насыщена достаточно, чтобы подпись на ней шла контрастным тоном.
INVERT_FROM = 3
PALETTE |= {f"level-{index}": pair for index, pair in enumerate(RAMP)}
MODES = ("light", "dark")


def num(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def tone(role: str, mode: str) -> str:
    return PALETTE[role][0 if mode == "light" else 1]


def wrap(body: str, limit: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in body.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) > limit and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


class Paint:
    """Примитивы для одной поверхности: каждый цвет уже разрешён в значение."""

    def __init__(self, mode: str):
        self.mode = mode

    def fill(self, role: str) -> str:
        return f'fill="{tone(role, self.mode)}"'

    def stroke(self, role: str) -> str:
        return f'stroke="{tone(role, self.mode)}"'

    def text(
        self,
        x: float,
        y: float,
        body: str,
        *,
        role: str = "ink",
        size: float = 13,
        weight: int | None = None,
        anchor: str | None = None,
    ) -> str:
        bold = f' font-weight="{weight}"' if weight else ""
        place = f' text-anchor="{anchor}"' if anchor else ""
        return (
            f'<text x="{num(x)}" y="{num(y)}" font-size="{num(size)}" '
            f"{self.fill(role)}{bold}{place}>{escape(body)}</text>"
        )

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        role: str,
        *,
        radius: float = 3,
        stroke: str | None = None,
    ) -> str:
        edge = f' {self.stroke(stroke)} stroke-width="1"' if stroke else ""
        return (
            f'<rect x="{num(x)}" y="{num(y)}" width="{num(width)}" height="{num(height)}" '
            f'rx="{num(radius)}" {self.fill(role)}{edge}/>'
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, role: str, width: float = 1) -> str:
        return (
            f'<line x1="{num(x1)}" y1="{num(y1)}" x2="{num(x2)}" y2="{num(y2)}" '
            f'{self.stroke(role)} stroke-width="{num(width)}"/>'
        )

    def dot(self, x: float, y: float, radius: float, role: str, edge: str = "surface") -> str:
        return (
            f'<circle cx="{num(x)}" cy="{num(y)}" r="{num(radius)}" {self.fill(role)} '
            f'{self.stroke(edge)} stroke-width="1.5"/>'
        )

    def polygon(self, points: list[tuple[float, float]], fill: str, stroke: str) -> str:
        path = " ".join(f"{num(x)},{num(y)}" for x, y in points)
        return (
            f'<polygon points="{path}" {self.fill(fill)} {self.stroke(stroke)} '
            f'stroke-width="2" stroke-linejoin="round"/>'
        )

    def legend(self, x: float, y: float, items: list[tuple[str, str]], gap: float = 9) -> list[str]:
        parts: list[str] = []
        for name, role in items:
            parts.append(self.rect(x, y, 10, 10, role, radius=2))
            parts.append(self.text(x + 15, y + 9, name, role="ink2", size=11))
            x += 15 + len(name) * 6.2 + gap
        return parts

    def frame(self, width: float, height: float, title: str, desc: str, body: list[str]) -> str:
        """Готовая фигура: подписанная карточка под эту поверхность."""
        return "\n".join(
            [
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{num(width)}" '
                f'height="{num(height)}" viewBox="0 0 {num(width)} {num(height)}" role="img" '
                f'font-family="{FONT}">',
                f"<title>{escape(title)}</title>",
                f"<desc>{escape(desc)}</desc>",
                self.rect(0, 0, width, height, "surface", radius=0),
                self.text(24, 34, title, role="ink", size=15, weight=600),
                *[part for part in body if part],
                "</svg>",
            ]
        )


def level_role(level: int) -> str:
    return f"level-{max(0, min(level, len(RAMP) - 1))}"


def label_for(dimension: dict) -> str:
    return dimension.get("short") or dimension["name"]


# --- Радар уровней -------------------------------------------------------------


def radar(result: Result, mode: str) -> str:
    paint = Paint(mode)
    width, height = 760, 600
    cx, cy, radius = 380, 320, 190
    rubric = result.rubric
    steps = rubric.max_level
    items = result.dimensions
    count = len(items)
    body: list[str] = []

    def point(index: int, value: float) -> tuple[float, float]:
        angle = -math.pi / 2 + 2 * math.pi * index / count
        reach = radius * value / steps
        return cx + reach * math.cos(angle), cy + reach * math.sin(angle)

    for step in range(1, steps + 1):
        ring = [point(index, step) for index in range(count)]
        path = " ".join(f"{num(x)},{num(y)}" for x, y in ring)
        body.append(
            f'<polygon points="{path}" fill="none" {paint.stroke("grid")} stroke-width="1"/>'
        )
    for index in range(count):
        x, y = point(index, steps)
        body.append(paint.line(cx, cy, x, y, "axis"))
    # Подписи колец стоят на верхней оси и накрываются контуром, поэтому под каждой
    # лежит прямоугольник цвета поверхности — иначе цифра тонет в заливке.
    for step in range(1, steps + 1):
        x, y = point(0, step)
        body.append(paint.rect(x + 3, y - 5, 13, 12, "surface", radius=2))
        body.append(paint.text(x + 6, y + 4, str(step), role="muted", size=10))

    scored = [(index, item) for index, item in enumerate(items) if item.scored]
    if len(scored) == count:
        body.append(
            paint.polygon(
                [point(index, item.level or 0) for index, item in scored], "accentfill", "accent"
            )
        )
    else:
        # С пробелами замкнутый контур врал бы: вместо него — лучи до уровня.
        for index, item in scored:
            x, y = point(index, item.level or 0)
            body.append(paint.line(cx, cy, x, y, "accent", 2))
    for index, item in scored:
        x, y = point(index, item.level or 0)
        body.append(paint.dot(x, y, 4.5, "accent"))

    for index, item in enumerate(items):
        angle = -math.pi / 2 + 2 * math.pi * index / count
        lx, ly = cx + (radius + 26) * math.cos(angle), cy + (radius + 26) * math.sin(angle)
        anchor = "middle"
        if math.cos(angle) > 0.2:
            anchor = "start"
        elif math.cos(angle) < -0.2:
            anchor = "end"
        mark = str(item.level) if item.scored else "—"
        name = label_for(item.dimension)
        role = "ink" if item.scored else "muted"
        body.append(paint.text(lx, ly, name, role=role, size=12, weight=500, anchor=anchor))
        body.append(
            paint.text(
                lx, ly + 14, mark, role="accent" if item.scored else "muted", size=11, anchor=anchor
            )
        )

    note = f"Шкала 0–{steps}."
    if len(scored) != count:
        note += " «—» — измерение не оценено, это не ноль; контур по таким осям не замкнут."
    body.append(paint.text(24, height - 20, note, role="muted", size=11))
    title = f"Уровни зрелости: {result.assessment.name}"
    desc = (
        "Радар: по каждому измерению рубрики отложен уровень зрелости от 0 до "
        f"{steps}. Неоцененные измерения помечены прочерком."
    )
    return paint.frame(width, height, title, desc, body)


# --- Полосы по измерениям ------------------------------------------------------


def scorecard(result: Result, mode: str) -> str:
    paint = Paint(mode)
    rubric = result.rubric
    left, bar_left, bar_width = 24, 250, 330
    row_height, group_gap = 26, 30
    rows = sum(len(rubric.in_group(group["id"])) for group in rubric.groups)
    height = 70 + rows * row_height + len(rubric.groups) * group_gap + 40
    width = 760
    body: list[str] = []
    y = 70
    for group in rubric.groups:
        score = next(item for item in result.groups if item.group["id"] == group["id"])
        mark = (
            f"{score.score:.0f} из 100 ({score.covered} из {score.total})"
            if score.covered
            else "не оценено"
        )
        body.append(
            paint.text(
                left,
                y,
                f"{group['name']} — {mark}",
                role="ink2" if score.covered else "muted",
                size=12,
                weight=600,
            )
        )
        y += 16
        for dimension in rubric.in_group(group["id"]):
            item = result.by_id(dimension["id"])
            assert item is not None
            body.append(paint.rect(bar_left, y, bar_width, 14, "card", radius=3))
            for step in range(1, rubric.max_level):
                x = bar_left + bar_width * step / rubric.max_level
                body.append(paint.line(x, y, x, y + 14, "grid"))
            if item.scored:
                filled = bar_width * (item.level or 0) / rubric.max_level
                if filled > 0:
                    body.append(
                        paint.rect(bar_left, y, filled, 14, level_role(item.level or 0), radius=3)
                    )
                mark = f"{item.level} · {rubric.level_name(item.level or 0)}"
            else:
                mark = "не оценено"
            body.append(
                paint.text(
                    left,
                    y + 11,
                    f"{label_for(dimension)} (вес {num(dimension['weight'])})",
                    role="ink" if item.scored else "muted",
                    size=12,
                )
            )
            body.append(
                paint.text(
                    bar_left + bar_width + 10,
                    y + 11,
                    mark,
                    role="ink2" if item.scored else "muted",
                    size=11,
                )
            )
            if dimension.get("blocking"):
                body.append(
                    paint.text(bar_left - 12, y + 11, "!", role="critical", size=12, weight=700)
                )
            y += row_height
        y += group_gap - 16
    body.append(
        paint.text(
            left,
            height - 20,
            "«!» — блокирующее измерение: уровень 0–1 опускает решение по проекту.",
            role="muted",
            size=11,
        )
    )
    title = f"Карта оценки: {result.assessment.name}"
    desc = (
        "Полосы по измерениям рубрики, сгруппированные по четырём группам; у каждого "
        "измерения показан его вес и уровень."
    )
    return paint.frame(width, height, title, desc, body)


# --- Матрица рисков ------------------------------------------------------------

RISK_AXIS = ("Низкое", "Среднее", "Высокое")


def risk_matrix(result: Result, mode: str) -> str:
    paint = Paint(mode)
    cell, left, top = 150, 150, 80
    width, height = left + 3 * cell + 30, top + 3 * cell + 90
    body: list[str] = []
    buckets: dict[tuple[int, int], list[dict]] = {}
    for risk in result.assessment.risks:
        key = (RANKS[risk["probability"]], RANKS[risk["impact"]])
        buckets.setdefault(key, []).append(risk)

    for probability in range(3):
        row = 2 - probability  # высокая вероятность наверху
        for impact in range(3):
            x, y = left + impact * cell, top + row * cell
            weight = probability + impact
            body.append(paint.rect(x, y, cell - 4, cell - 4, level_role(weight), radius=4))
            inside = buckets.get((probability, impact), [])
            role = "oncell" if weight >= INVERT_FROM else "ink"
            # В ячейке стоят только идентификаторы: названия целиком идут в таблице
            # под фигурой, а обрезанное на полуслове название хуже, чем его отсутствие.
            if inside:
                line = y + 34
                for piece in wrap(", ".join(item["id"] for item in inside), 16):
                    body.append(paint.text(x + 14, line, piece, role=role, size=16, weight=600))
                    line += 20
                body.append(
                    paint.text(
                        x + 14,
                        y + cell - 24,
                        f"{len(inside)} риск(ов)",
                        role=role,
                        size=11,
                    )
                )
            else:
                body.append(paint.text(x + 14, y + 34, "—", role=role, size=16))
        body.append(
            paint.text(
                left - 12,
                top + row * cell + (cell - 4) / 2,
                RISK_AXIS[probability],
                role="ink2",
                size=12,
                anchor="end",
            )
        )
    for impact in range(3):
        body.append(
            paint.text(
                left + impact * cell + (cell - 4) / 2,
                top + 3 * cell + 18,
                RISK_AXIS[impact],
                role="ink2",
                size=12,
                anchor="middle",
            )
        )
    body.append(
        paint.text(
            left + 1.5 * cell,
            top + 3 * cell + 42,
            "Влияние →",
            role="muted",
            size=11,
            anchor="middle",
        )
    )
    body.append(paint.text(24, top - 14, "↑ Вероятность", role="muted", size=11))
    critical = len(result.critical_risks)
    body.append(
        paint.text(
            24,
            height - 18,
            f"Критических рисков (вероятность + влияние ≥ 3): {critical} из "
            f"{len(result.assessment.risks)}. Названия — в таблице под картой.",
            role="muted",
            size=11,
        )
    )
    title = f"Карта рисков: {result.assessment.name}"
    desc = (
        "Матрица 3 × 3: вероятность по вертикали, влияние по горизонтали; в ячейках "
        "идентификаторы рисков из реестра."
    )
    return paint.frame(width, height, title, desc, body)


# --- Портфель проектов ---------------------------------------------------------


def portfolio_matrix(results: list[Result], rubric: Rubric, mode: str) -> str:
    """Готовность (взвешенный балл) против ценности для бизнеса, по всем проектам."""
    paint = Paint(mode)
    width, height = 760, 560
    left, right, top, bottom = 90, 700, 70, 460
    body: list[str] = []
    body.append(paint.rect(left, top, right - left, bottom - top, "card", radius=4))
    for share in (0.25, 0.5, 0.75):
        x = left + (right - left) * share
        body.append(paint.line(x, top, x, bottom, "grid"))
    for step in range(1, rubric.max_level):
        y = bottom - (bottom - top) * step / rubric.max_level
        body.append(paint.line(left, y, right, y, "grid"))
    # Порог решения «идём» и уровень 2 делят поле на четыре квадранта.
    threshold = rubric.verdict("go")["min_score"]
    x_cut = left + (right - left) * threshold / 100
    y_cut = bottom - (bottom - top) * 2 / rubric.max_level
    body.append(paint.line(x_cut, top, x_cut, bottom, "axis", 1.5))
    body.append(paint.line(left, y_cut, right, y_cut, "axis", 1.5))
    body.append(
        paint.text(x_cut + 6, top + 16, f"готовность ≥ {num(threshold)}", role="muted", size=10)
    )

    for row in sorted(results, key=lambda item: item.overall):
        value = row.by_id("business-value")
        level = value.level if value and value.scored else 0
        x = left + (right - left) * min(row.overall, 100) / 100
        y = bottom - (bottom - top) * level / rubric.max_level
        size = 9 + 4 * len(row.blockers)
        role = "critical" if row.blockers else ("accent" if row.overall >= threshold else "warning")
        body.append(paint.dot(x, y, size, role))
        body.append(
            paint.text(x + size + 6, y + 4, row.assessment.code, role="ink", size=11, weight=600)
        )
        body.append(paint.text(x + size + 6, y + 17, row.verdict["name"], role="muted", size=10))

    body.append(
        paint.text(
            (left + right) / 2,
            bottom + 34,
            "Готовность, балл 0–100 →",
            role="ink2",
            size=12,
            anchor="middle",
        )
    )
    body.append(paint.text(24, top - 12, "↑ Ценность для бизнеса, уровень", role="ink2", size=12))
    for step in range(rubric.max_level + 1):
        y = bottom - (bottom - top) * step / rubric.max_level
        body.append(paint.text(left - 10, y + 4, str(step), role="muted", size=10, anchor="end"))
    body.extend(
        paint.legend(
            24,
            height - 60,
            [
                ("есть блокирующий пробел", "critical"),
                ("ниже порога", "warning"),
                ("на уровне порога", "accent"),
            ],
        )
    )
    body.append(
        paint.text(
            24,
            height - 20,
            "Размер точки растёт с числом блокирующих пробелов.",
            role="muted",
            size=11,
        )
    )
    title = "Портфель проектов: готовность против ценности"
    desc = (
        "Точечная диаграмма: по горизонтали взвешенная готовность проекта, по вертикали "
        "уровень ценности для бизнеса; подписан код проекта и решение по нему."
    )
    return paint.frame(width, height, title, desc, body)


# --- План работ в коммерческом предложении -------------------------------------


def timeline(proposal: Proposal, mode: str) -> str:
    """Этапы предложения по неделям: что когда заканчивается и чем."""
    paint = Paint(mode)
    left, right, top = 250, 730, 80
    row_height = 58
    width = 760
    height = top + len(proposal.stages) * row_height + 80
    total = proposal.weeks or 1
    body: list[str] = []

    # Сетка по неделям: шаг подбирается так, чтобы делений было не больше десятка.
    step = max(1, round(total / 8))
    week = 0
    while week <= total:
        x = left + (right - left) * week / total
        body.append(paint.line(x, top - 8, x, top + len(proposal.stages) * row_height, "grid"))
        body.append(paint.text(x, top - 14, f"{week:g}", role="muted", size=10, anchor="middle"))
        week += step
    body.append(paint.text(left - 8, top - 14, "неделя", role="muted", size=10, anchor="end"))

    start = 0.0
    for index, stage in enumerate(proposal.stages):
        y = top + index * row_height + 10
        x1 = left + (right - left) * start / total
        x2 = left + (right - left) * (start + stage["weeks"]) / total
        role = level_role(min(index + 1, len(RAMP) - 1))
        body.append(paint.rect(x1, y, max(x2 - x1 - 3, 6), 24, role, radius=4))
        body.append(
            paint.text(24, y + 16, f"{index + 1}. {stage['name']}", role="ink", size=12, weight=500)
        )
        mark = f"{stage['weeks']:g} нед."
        if stage.get("price"):
            mark += f" · {stage['price']}"
        # Подпись идёт внутри полосы, если помещается, и справа от неё, если нет; у
        # последнего этапа справа места не остаётся, поэтому она прижимается к концу.
        estimated = len(mark) * 5.8
        if x2 - x1 > estimated + 16:
            body.append(
                paint.text(
                    x1 + 8,
                    y + 16,
                    mark,
                    role="oncell" if index + 1 >= INVERT_FROM else "ink2",
                    size=11,
                )
            )
        elif x2 + 8 + estimated < width - 20:
            body.append(paint.text(x2 + 8, y + 16, mark, role="ink2", size=11))
        else:
            body.append(paint.text(x1 - 8, y + 16, mark, role="ink2", size=11, anchor="end"))
        deliverable = stage["deliverables"][0]
        body.append(
            paint.text(24, y + 34, wrap(deliverable, 30)[0] + "…", role="muted", size=10)
            if len(deliverable) > 30
            else paint.text(24, y + 34, deliverable, role="muted", size=10)
        )
        start += stage["weeks"]

    body.append(
        paint.text(
            24,
            height - 24,
            f"Суммарный срок — {total:g} недель. Переход между этапами — по результату "
            f"предыдущего, а не по календарю.",
            role="muted",
            size=11,
        )
    )
    title = f"План работ: {proposal.name}"
    desc = (
        "Горизонтальная диаграмма этапов: длина полосы — длительность этапа в неделях, "
        "рядом указан срок, стоимость и основной результат."
    )
    return paint.frame(width, height, title, desc, body)


# --- Запись файлов -------------------------------------------------------------


def figures(result: Result) -> dict[str, Callable[[str], str]]:
    return {
        f"radar.{result.assessment.id}": lambda mode: radar(result, mode),
        f"scorecard.{result.assessment.id}": lambda mode: scorecard(result, mode),
        f"risks.{result.assessment.id}": lambda mode: risk_matrix(result, mode),
    }


def write_figures(assets, results: list[Result], rubric: Rubric) -> list:
    """Каждая фигура пишется дважды: `name.svg` и `name.dark.svg`."""
    assets.mkdir(parents=True, exist_ok=True)
    builders: dict[str, Callable[[str], str]] = {}
    for result in results:
        if result.assessment.risks:
            builders.update(figures(result))
        else:
            builders.update(
                {
                    key: value
                    for key, value in figures(result).items()
                    if not key.startswith("risks.")
                }
            )
    if len(results) > 1:
        builders["portfolio"] = lambda mode: portfolio_matrix(results, rubric, mode)
    return _write(assets, builders)


def write_proposal_figures(assets, proposals: list[Proposal]) -> list:
    assets.mkdir(parents=True, exist_ok=True)
    builders: dict[str, Callable[[str], str]] = {
        f"timeline.{proposal.id}": (lambda item: lambda mode: timeline(item, mode))(proposal)
        for proposal in proposals
    }
    return _write(assets, builders)


def _write(assets, builders: dict[str, Callable[[str], str]]) -> list:
    written = []
    for name, build in builders.items():
        for mode in MODES:
            suffix = ".svg" if mode == "light" else ".dark.svg"
            path = assets / f"{name}{suffix}"
            path.write_text(build(mode) + "\n", encoding="utf-8")
            written.append(path)
    return written
