"""Арифметика оценки: уровни измерений → взвешенный балл, решение, пробелы, риски.

Правила, которые стоит знать, прежде чем читать числа в отчёте.

Балл считается только по оцененным измерениям. Черновик с четырьмя заполненными
измерениями из двенадцати честно показывает балл по этим четырём и отдельно — охват;
подмешивать ноль за неоцененное значило бы выдавать незнание за плохую оценку.

Решение по проекту не выводится из средней напрямую. Блокирующее измерение рубрики
(данные, безопасность, эвалы) на уровне 0-1 опускает решение до «сначала закрыть
пробелы», какой бы высокой ни была средняя: в агентных проектах именно эти три
пробела дороже всего закрывать после запуска. Ручное решение в файле оценки уважается,
но расхождение с расчётным выносится в проверку — чтобы его объясняли, а не забывали.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .content import RANKS, Assessment, Rubric

# От этой суммы вероятности и влияния риск считается критическим (2+2 = «высокий ×
# высокий», 1+2 — «средний × высокий»).
CRITICAL_RISK = 3
# Расхождение между уровнем измерения и средним по его критериям, после которого
# проверка просит объяснить несогласие.
DRIFT = 1.0
EFFORT_COST = {"s": 1.0, "m": 2.0, "l": 3.0}


@dataclass
class DimensionScore:
    dimension: dict
    level: int | None
    confidence: str | None
    percent: float
    weight: float
    criteria: dict[str, int]
    criteria_mean: float | None
    finding: str
    strength: str
    risk: str
    recommendation: str
    evidence: list[str]

    @property
    def id(self) -> str:
        return self.dimension["id"]

    @property
    def name(self) -> str:
        return self.dimension["name"]

    @property
    def group(self) -> str:
        return self.dimension["group"]

    @property
    def blocking(self) -> bool:
        return bool(self.dimension.get("blocking"))

    @property
    def scored(self) -> bool:
        return self.level is not None

    @property
    def drift(self) -> float:
        """Насколько уровень измерения расходится со средним по его критериям."""
        if self.level is None or self.criteria_mean is None:
            return 0.0
        return abs(self.level - self.criteria_mean)

    @property
    def gap(self) -> float:
        """Сколько взвешенного балла проект теряет на этом измерении."""
        if self.level is None:
            return 0.0
        return self.weight * (100 - self.percent) / 100


@dataclass
class GroupScore:
    group: dict
    score: float
    covered: int
    total: int


@dataclass
class Result:
    assessment: Assessment
    rubric: Rubric
    dimensions: list[DimensionScore]
    overall: float
    computed_verdict: dict
    verdict: dict
    blockers: list[DimensionScore]
    groups: list[GroupScore]
    notes: list[str] = field(default_factory=list)

    @property
    def scored(self) -> list[DimensionScore]:
        return [item for item in self.dimensions if item.scored]

    @property
    def coverage(self) -> float:
        return 100 * len(self.scored) / len(self.dimensions) if self.dimensions else 0.0

    @property
    def overridden(self) -> bool:
        return self.verdict["id"] != self.computed_verdict["id"]

    @property
    def strengths(self) -> list[DimensionScore]:
        at_least = [item for item in self.scored if (item.level or 0) >= 3]
        return sorted(at_least, key=lambda item: (-(item.level or 0), -item.weight, item.name))

    @property
    def gaps(self) -> list[DimensionScore]:
        weak = [item for item in self.scored if (item.level or 0) <= 2]
        return sorted(weak, key=lambda item: (-item.gap, item.name))

    @property
    def critical_risks(self) -> list[dict]:
        return [item for item in self.assessment.risks if risk_weight(item) >= CRITICAL_RISK]

    def by_id(self, dimension: str) -> DimensionScore | None:
        return next((item for item in self.dimensions if item.id == dimension), None)

    def plan(self) -> list[tuple[int, list[dict]]]:
        """План по горизонтам: внутри горизонта — по отдаче на усилие."""
        return [
            (horizon, sorted(self.assessment.actions_for(horizon), key=action_priority))
            for horizon in (30, 60, 90)
        ]


def risk_weight(risk: dict) -> int:
    return RANKS[risk["probability"]] + RANKS[risk["impact"]]


def action_priority(action: dict) -> tuple[float, str]:
    """Сначала то, что даёт больше при меньших усилиях; ничья — по заголовку."""
    impact = RANKS.get(action.get("impact", "medium"), 1) + 1
    effort = EFFORT_COST.get(action.get("effort", "m"), 2.0)
    return (-impact / effort, action["title"])


def percent_of(level: int, max_level: int) -> float:
    return 100 * level / max_level if max_level else 0.0


def score(assessment: Assessment, rubric: Rubric) -> Result:
    """Полный расчёт по одной оценке. Ничего не читает с диска и не мутирует вход."""
    dimensions: list[DimensionScore] = []
    for dimension in rubric.dimensions:
        raw = assessment.scores.get(dimension["id"])
        criteria = dict(raw.get("criteria", {})) if raw else {}
        mean = sum(criteria.values()) / len(criteria) if criteria else None
        level = raw["level"] if raw else None
        dimensions.append(
            DimensionScore(
                dimension=dimension,
                level=level,
                confidence=(raw or {}).get("confidence"),
                percent=percent_of(level, rubric.max_level) if level is not None else 0.0,
                weight=dimension["weight"],
                criteria=criteria,
                criteria_mean=mean,
                finding=(raw or {}).get("finding", ""),
                strength=(raw or {}).get("strength", ""),
                risk=(raw or {}).get("risk", ""),
                recommendation=(raw or {}).get("recommendation", ""),
                evidence=list((raw or {}).get("evidence", [])),
            )
        )

    scored = [item for item in dimensions if item.scored]
    weight = sum(item.weight for item in scored)
    overall = sum(item.weight * item.percent for item in scored) / weight if weight else 0.0

    blockers = [item for item in scored if item.blocking and (item.level or 0) <= 1]
    computed = verdict_for(overall, rubric)
    if blockers:
        computed = cap_verdict(computed, "fix", rubric)
    chosen = computed
    manual = assessment.verdict_note.get("decision")
    if manual:
        chosen = rubric.verdict(manual)

    groups = []
    for group in rubric.groups:
        inside = [item for item in dimensions if item.group == group["id"]]
        covered = [item for item in inside if item.scored]
        group_weight = sum(item.weight for item in covered)
        groups.append(
            GroupScore(
                group=group,
                score=(
                    sum(item.weight * item.percent for item in covered) / group_weight
                    if group_weight
                    else 0.0
                ),
                covered=len(covered),
                total=len(inside),
            )
        )

    return Result(
        assessment=assessment,
        rubric=rubric,
        dimensions=dimensions,
        overall=overall,
        computed_verdict=computed,
        verdict=chosen,
        blockers=blockers,
        groups=groups,
        notes=warnings(assessment, dimensions, computed, chosen),
    )


def verdict_for(overall: float, rubric: Rubric) -> dict:
    for item in rubric.verdicts:  # отсортированы по порогу вниз
        if overall >= item["min_score"]:
            return item
    return rubric.verdicts[-1]


def cap_verdict(current: dict, ceiling_id: str, rubric: Rubric) -> dict:
    """Не выше указанного решения; ниже — оставить как есть."""
    ceiling = rubric.verdict(ceiling_id)
    return ceiling if current["min_score"] > ceiling["min_score"] else current


def warnings(
    assessment: Assessment,
    dimensions: list[DimensionScore],
    computed: dict,
    chosen: dict,
) -> list[str]:
    """То, что не ломает сборку, но должно попасть на глаза перед сдачей."""
    notes: list[str] = []
    for item in dimensions:
        if item.drift > DRIFT:
            notes.append(
                f"{item.id}: уровень {item.level} расходится со средним по критериям "
                f"{item.criteria_mean:.1f} — объясните в находке или поправьте уровень"
            )
        if item.scored and item.confidence == "low" and (item.level or 0) >= 3:
            notes.append(
                f"{item.id}: уровень {item.level} при низкой уверенности — "
                f"высокая оценка держится на одном непроверенном источнике"
            )
    if chosen["id"] != computed["id"]:
        rationale = assessment.verdict_note.get("rationale")
        notes.append(
            f"решение в файле «{chosen['name']}» вместо расчётного «{computed['name']}»"
            + ("" if rationale else " — и без обоснования в verdict.rationale")
        )
    covered = {item.id for item in dimensions if item.scored}
    for risk in assessment.risks:
        named = risk.get("dimension")
        if named and named not in covered:
            notes.append(f"риск {risk['id']} указывает на неоцененное измерение {named}")
    return notes


def portfolio(results: list[Result]) -> list[dict]:
    """Строки для сводной таблицы по всем проектам, сильные пробелы впереди."""
    rows = []
    for result in results:
        value = result.by_id("business-value")
        rows.append(
            {
                "id": result.assessment.id,
                "code": result.assessment.code,
                "name": result.assessment.name,
                "client": result.assessment.client,
                "stage": result.assessment.project["stage"],
                "pattern": result.assessment.project["pattern"],
                "assessed": result.assessment.assessed,
                "status": result.assessment.status,
                "overall": result.overall,
                "coverage": result.coverage,
                "verdict": result.verdict,
                "value_level": value.level if value else None,
                "blockers": [item.id for item in result.blockers],
                "critical_risks": len(result.critical_risks),
            }
        )
    return sorted(rows, key=lambda row: (-row["overall"], row["name"]))
