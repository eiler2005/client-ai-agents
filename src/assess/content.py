"""Загрузка и проверка содержимого: рубрика, оценки, профиль компании, предложения.

Проверка идёт в два слоя. Схемы JSON Schema держат форму файла: типы, перечисления,
обязательные поля. Поверх них — связи, которые схемой не выразить: ссылка на
измерение рубрики, ссылка на источник, уникальность идентификаторов, а для оценки со
статусом `final` — полнота. Файл со статусом `draft` разрешено оставлять неполным:
оценка пишется по ходу интервью, и ругаться на каждую незаполненную строку бессмысленно.

Профиль компании живёт по тем же правилам, что и оценка: у каждой цифры есть источник
и дата, на которую она верна. Коммерческое предложение собирается из профиля и ссылается
на его идентификаторы — выдумать в КП услугу или кейс, которого нет в профиле, нельзя.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

CONTENT = Path(__file__).resolve().parents[1] / "content"
SCHEMA = CONTENT / "schema"
LEVELS = (0, 1, 2, 3, 4)
HORIZONS = (30, 60, 90)
RANKS = {"low": 0, "medium": 1, "high": 2}


class ContentError(Exception):
    """Все найденные проблемы разом: по одной строке на проблему."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__(f"{len(problems)} проблем(ы) в содержимом")


def _plain(value: Any) -> Any:
    """Даты YAML превращает в объекты; схема ждёт строку ISO."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()[:10]
    return value


def read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return _plain(yaml.safe_load(handle))


def validate(data: Any, schema_name: str, label: str) -> list[str]:
    schema = json.loads((SCHEMA / schema_name).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    problems = []
    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
        where = "/".join(str(part) for part in error.path) or "<корень>"
        problems.append(f"{label}: {where}: {error.message}")
    return problems


class Rubric:
    """Рубрика с готовыми индексами: обращаться по id, а не искать в списке."""

    def __init__(self, data: dict):
        self.data = data
        self.version: int = data["version"]
        self.updated: str = data["updated"]
        self.scale: list[dict] = data["scale"]
        self.verdicts: list[dict] = sorted(
            data["verdicts"], key=lambda item: item["min_score"], reverse=True
        )
        self.groups: list[dict] = data["groups"]
        self.dimensions: list[dict] = data["dimensions"]
        self.by_id: dict[str, dict] = {item["id"]: item for item in self.dimensions}
        self.scale_by_level: dict[int, dict] = {item["level"]: item for item in self.scale}
        self.confidence: dict[str, dict] = {item["id"]: item for item in data.get("confidence", [])}
        self.patterns: dict[str, dict] = {item["id"]: item for item in data.get("patterns", [])}
        self.stages: dict[str, dict] = {item["id"]: item for item in data.get("stages", [])}
        self.groups_by_id: dict[str, dict] = {item["id"]: item for item in self.groups}
        self.max_level: int = max(self.scale_by_level)

    @property
    def weight_total(self) -> float:
        return sum(item["weight"] for item in self.dimensions)

    def in_group(self, group: str) -> list[dict]:
        return [item for item in self.dimensions if item["group"] == group]

    def criteria_ids(self, dimension: str) -> set[str]:
        return {item["id"] for item in self.by_id[dimension]["criteria"]}

    def level_name(self, level: int) -> str:
        return self.scale_by_level[level]["name"]

    def verdict(self, verdict_id: str) -> dict:
        for item in self.verdicts:
            if item["id"] == verdict_id:
                return item
        raise KeyError(verdict_id)


def load_rubric(content: Path | None = None) -> Rubric:
    root = content or CONTENT
    data = read_yaml(root / "rubric.yaml")
    problems = validate(data, "rubric.schema.json", "rubric.yaml")
    if not problems:
        problems += _rubric_links(data)
    if problems:
        raise ContentError(problems)
    return Rubric(data)


def _rubric_links(data: dict) -> list[str]:
    problems: list[str] = []
    groups = {item["id"] for item in data["groups"]}
    seen_dimensions: set[str] = set()
    seen_criteria: set[str] = set()
    levels = {item["level"] for item in data["scale"]}
    for dimension in data["dimensions"]:
        name = dimension["id"]
        if name in seen_dimensions:
            problems.append(f"rubric.yaml: измерение {name} объявлено дважды")
        seen_dimensions.add(name)
        if dimension["group"] not in groups:
            problems.append(f"rubric.yaml: {name}: неизвестная группа {dimension['group']}")
        for anchor in dimension["anchors"]:
            if int(anchor) not in levels:
                problems.append(
                    f"rubric.yaml: {name}: опорное описание для уровня {anchor} вне шкалы"
                )
        for criterion in dimension["criteria"]:
            if criterion["id"] in seen_criteria:
                problems.append(f"rubric.yaml: критерий {criterion['id']} объявлен дважды")
            seen_criteria.add(criterion["id"])
    used = {dimension["group"] for dimension in data["dimensions"]}
    for group in groups - used:
        problems.append(f"rubric.yaml: в группе {group} нет ни одного измерения")
    return problems


class Assessment:
    """Одна оценка проекта. Доступ к полям — через свойства, значения по умолчанию здесь."""

    def __init__(self, data: dict, path: Path):
        self.data = data
        self.path = path
        self.id: str = data["id"]
        self.status: str = data["status"]
        self.project: dict = data["project"]
        self.scores: dict[str, dict] = data["scores"]
        self.sources: list[dict] = data.get("sources", [])
        self.risks: list[dict] = data.get("risks", [])
        self.actions: list[dict] = data.get("actions", [])
        self.highlights: list[str] = data.get("highlights", [])
        self.verdict_note: dict = data.get("verdict", {})

    @property
    def name(self) -> str:
        return self.project["name"]

    @property
    def client(self) -> str:
        return self.project["client"]

    @property
    def code(self) -> str:
        return self.project.get("client_code") or self.id.upper()

    @property
    def assessed(self) -> str:
        return self.project["assessed"]

    def source(self, source_id: str) -> dict | None:
        return next((item for item in self.sources if item["id"] == source_id), None)

    def actions_for(self, horizon: int) -> list[dict]:
        return [item for item in self.actions if item["horizon"] == horizon]


def load_assessments(where: Path, rubric: Rubric, *, strict: bool = True) -> list[Assessment]:
    """Все оценки из каталога (или один файл), отсортированные по дате оценки."""
    paths = sorted(where.glob("*.yaml")) if where.is_dir() else [where]
    if not paths:
        raise ContentError([f"{where}: не найдено ни одного файла оценки (*.yaml)"])
    problems: list[str] = []
    loaded: list[Assessment] = []
    seen: dict[str, Path] = {}
    for path in paths:
        data = read_yaml(path)
        label = path.name
        if not isinstance(data, dict):
            problems.append(f"{label}: ожидался объект верхнего уровня")
            continue
        found = validate(data, "assessment.schema.json", label)
        if found:
            problems += found
            continue
        if data["id"] != path.stem:
            problems.append(f"{label}: id «{data['id']}» не совпадает с именем файла")
        if data["id"] in seen:
            problems.append(f"{label}: id «{data['id']}» уже занят файлом {seen[data['id']].name}")
        seen[data["id"]] = path
        problems += _assessment_links(data, rubric, label)
        loaded.append(Assessment(data, path))
    if problems and strict:
        raise ContentError(problems)
    return sorted(loaded, key=lambda item: (item.assessed, item.id))


def _assessment_links(data: dict, rubric: Rubric, label: str) -> list[str]:
    problems: list[str] = []
    source_ids = {item["id"] for item in data.get("sources", [])}
    if len(source_ids) != len(data.get("sources", [])):
        problems.append(f"{label}: идентификаторы источников повторяются")
    stage = data["project"]["stage"]
    if rubric.stages and stage not in rubric.stages:
        problems.append(f"{label}: неизвестная стадия «{stage}»")
    pattern = data["project"]["pattern"]
    if rubric.patterns and pattern not in rubric.patterns:
        problems.append(f"{label}: неизвестный тип решения «{pattern}»")

    for dimension, score in data["scores"].items():
        if dimension not in rubric.by_id:
            problems.append(f"{label}: scores/{dimension}: нет такого измерения в рубрике")
            continue
        known = rubric.criteria_ids(dimension)
        for criterion in score.get("criteria", {}):
            if criterion not in known:
                problems.append(
                    f"{label}: scores/{dimension}/criteria/{criterion}: "
                    f"критерий не принадлежит этому измерению"
                )
        for evidence in score.get("evidence", []):
            if evidence not in source_ids:
                problems.append(
                    f"{label}: scores/{dimension}: ссылка на источник «{evidence}» без описания "
                    f"в разделе sources"
                )

    for kind, items in (("risks", data.get("risks", [])), ("actions", data.get("actions", []))):
        ids: set[str] = set()
        for item in items:
            if item["id"] in ids:
                problems.append(f"{label}: {kind}: идентификатор «{item['id']}» повторяется")
            ids.add(item["id"])
            named = item.get("dimension")
            if named and named not in rubric.by_id:
                problems.append(f"{label}: {kind}/{item['id']}: нет измерения «{named}»")

    if data["status"] == "final":
        problems += _final_checks(data, rubric, label)
    return problems


def _final_checks(data: dict, rubric: Rubric, label: str) -> list[str]:
    """Что обязательно для готового отчёта и необязательно для черновика."""
    problems: list[str] = []
    missing = [item["id"] for item in rubric.dimensions if item["id"] not in data["scores"]]
    if missing:
        problems.append(f"{label}: status=final, но не оценены измерения: {', '.join(missing)}")
    for dimension, score in data["scores"].items():
        if "confidence" not in score:
            problems.append(f"{label}: scores/{dimension}: для final нужна уверенность оценки")
        if not score.get("evidence"):
            problems.append(f"{label}: scores/{dimension}: для final нужна ссылка на источник")
        if score["level"] <= 2 and not score.get("recommendation"):
            problems.append(
                f"{label}: scores/{dimension}: уровень {score['level']} без рекомендации"
            )
    if not data.get("highlights"):
        problems.append(f"{label}: status=final, но нет highlights для резюме")
    if not data.get("actions"):
        problems.append(f"{label}: status=final, но нет ни одного действия в плане")
    for action in data.get("actions", []):
        if not action.get("owner"):
            problems.append(f"{label}: actions/{action['id']}: для final нужен владелец")
    for risk in data.get("risks", []):
        if not risk.get("mitigation"):
            problems.append(f"{label}: risks/{risk['id']}: для final нужна мера реагирования")
    return problems


# --- Профиль компании ----------------------------------------------------------

# После этого срока факт считается устаревшим и его просят подтвердить перед отправкой.
# Выручка и численность меняются раз в год, поэтому порог — год с запасом.
STALE_AFTER_DAYS = 400


class Company:
    """Профиль компании с индексами по идентификаторам."""

    def __init__(self, data: dict):
        self.data = data
        self.version: int = data["version"]
        self.updated: str = data["updated"]
        self.organisation: dict = data["organisation"]
        self.facts: list[dict] = data["facts"]
        self.offerings: list[dict] = data["offerings"]
        self.sources: dict[str, dict] = {item["id"]: item for item in data["sources"]}
        self.industries: dict[str, dict] = {item["id"]: item for item in data.get("industries", [])}
        self.scenarios: list[dict] = data.get("scenarios", [])
        self.proof: list[dict] = data.get("proof", [])
        self.clients: list[dict] = data.get("clients", [])
        self.contacts: list[dict] = data.get("contacts", [])
        self.roles: list[dict] = data.get("roles", [])
        self.platform: dict = data.get("platform", {})
        self.stack: dict = data.get("stack", {})
        self.integrations: list[str] = data.get("integrations", [])
        self.security: list[str] = data.get("security", [])
        self.method: list[dict] = data.get("method", [])
        self.delivery: list[dict] = data.get("delivery", [])
        self.caveat: str = data.get("caveat", "")
        self.by_offering: dict[str, dict] = {item["id"]: item for item in self.offerings}
        self.by_fact: dict[str, dict] = {item["id"]: item for item in self.facts}
        self.by_proof: dict[str, dict] = {item["id"]: item for item in self.proof}
        self.by_contact: dict[str, dict] = {item["id"]: item for item in self.contacts}

    @property
    def name(self) -> str:
        return self.organisation["name"]

    def contacts_for(self, chosen: list[str] | None = None) -> list[dict]:
        """Контакты для карточки: названные в документе, иначе помеченные `default`."""
        if chosen:
            return [self.by_contact[item] for item in chosen if item in self.by_contact]
        default = [item for item in self.contacts if item.get("default")]
        return default or self.contacts[:1]

    def proof_for(self, industry: str | None, limit: int = 4) -> list[dict]:
        """Подтверждённый опыт для отрасли; при нехватке добирается общими кейсами."""
        matched = [item for item in self.proof if industry in item.get("industries", [])]
        rest = [item for item in self.proof if item not in matched]
        return (matched + rest)[:limit]

    def stale_facts(self, today: str | None = None) -> list[dict]:
        """Факты, чья дата старше порога: их просят подтвердить перед отправкой.

        Лицензии, сертификаты, год основания и партнёрства помечены `perennial`: их
        дата — это дата события, а не дата проверки, и напоминать о них нечего.
        """
        now = dt.date.fromisoformat(today) if today else dt.date.today()
        late = []
        for fact in self.facts:
            if fact.get("perennial"):
                continue
            age = (now - dt.date.fromisoformat(fact["as_of"])).days
            if age > STALE_AFTER_DAYS:
                late.append(fact)
        return late


def load_company(content: Path | None = None) -> Company:
    root = content or CONTENT
    data = read_yaml(root / "company.yaml")
    problems = validate(data, "company.schema.json", "company.yaml")
    if not problems:
        problems += _company_links(data)
    if problems:
        raise ContentError(problems)
    return Company(data)


def _company_links(data: dict) -> list[str]:
    """Каждая ссылка на источник, отрасль и услугу должна вести к существующему блоку."""
    problems: list[str] = []
    sources = {item["id"] for item in data["sources"]}
    industries = {item["id"] for item in data.get("industries", [])}
    offerings = {item["id"] for item in data["offerings"]}

    def check_source(where: str, value: str | None) -> None:
        if value and value not in sources:
            problems.append(f"company.yaml: {where}: нет источника «{value}»")

    for group in ("facts", "offerings", "scenarios", "proof", "clients", "industries"):
        for index, item in enumerate(data.get(group, [])):
            check_source(f"{group}/{item.get('id', index)}", item.get("source"))
    for key in ("method_source", "delivery_source"):
        check_source(key, data.get(key))
    if data.get("platform"):
        check_source("platform", data["platform"].get("source"))

    for item in data.get("proof", []):
        for industry in item.get("industries", []):
            if industry not in industries:
                problems.append(f"company.yaml: proof/{item['id']}: нет отрасли «{industry}»")
        named = item.get("offering")
        if named and named not in offerings:
            problems.append(f"company.yaml: proof/{item['id']}: нет услуги «{named}»")

    for group in ("facts", "offerings", "scenarios", "proof", "industries", "roles", "contacts"):
        ids = [item["id"] for item in data.get(group, [])]
        if len(ids) != len(set(ids)):
            problems.append(f"company.yaml: {group}: идентификаторы повторяются")
    for contact in data.get("contacts", []):
        if not any(contact.get(channel) for channel in ("email", "telegram", "phone")):
            problems.append(
                f"company.yaml: contacts/{contact['id']}: нужен хотя бы один канал связи"
            )
    return problems


# --- Коммерческие предложения --------------------------------------------------


class Proposal:
    """Одно коммерческое предложение."""

    def __init__(self, data: dict, path: Path):
        self.data = data
        self.path = path
        self.id: str = data["id"]
        self.status: str = data["status"]
        self.date: str = data["date"]
        self.valid_until: str | None = data.get("valid_until")
        self.client: dict = data["client"]
        self.project: dict = data["project"]
        self.context: dict = data["context"]
        self.scope: dict = data["scope"]
        self.stages: list[dict] = data["stages"]
        self.team: list[dict] = data.get("team", [])
        self.commercials: dict = data.get("commercials", {})
        self.risks: list[dict] = data.get("risks", [])
        self.about: dict = data.get("about", {})
        self.next_steps: list[str] = data.get("next_steps", [])
        self.offerings: list[str] = data.get("offerings", [])

    @property
    def name(self) -> str:
        return self.project["name"]

    @property
    def client_name(self) -> str:
        return self.client["name"]

    @property
    def industry(self) -> str:
        return self.client["industry"]

    @property
    def assessment_id(self) -> str | None:
        return self.project.get("assessment")

    @property
    def weeks(self) -> float:
        return sum(stage["weeks"] for stage in self.stages)


def load_proposals(where: Path, company: Company, *, strict: bool = True) -> list[Proposal]:
    paths = sorted(where.glob("*.yaml")) if where.is_dir() else [where]
    if not paths:
        raise ContentError([f"{where}: не найдено ни одного файла предложения (*.yaml)"])
    problems: list[str] = []
    loaded: list[Proposal] = []
    for path in paths:
        data = read_yaml(path)
        label = path.name
        if not isinstance(data, dict):
            problems.append(f"{label}: ожидался объект верхнего уровня")
            continue
        found = validate(data, "proposal.schema.json", label)
        if found:
            problems += found
            continue
        if data["id"] != path.stem:
            problems.append(f"{label}: id «{data['id']}» не совпадает с именем файла")
        problems += _proposal_links(data, company, label)
        loaded.append(Proposal(data, path))
    if problems and strict:
        raise ContentError(problems)
    return sorted(loaded, key=lambda item: (item.date, item.id))


def _proposal_links(data: dict, company: Company, label: str) -> list[str]:
    problems: list[str] = []
    if data["client"]["industry"] not in company.industries:
        problems.append(f"{label}: неизвестная отрасль «{data['client']['industry']}»")
    for offering in data.get("offerings", []):
        if offering not in company.by_offering:
            problems.append(f"{label}: offerings: нет услуги «{offering}» в профиле компании")
    about = data.get("about", {})
    for fact in about.get("facts", []):
        if fact not in company.by_fact:
            problems.append(f"{label}: about/facts: нет факта «{fact}» в профиле компании")
    for proof in about.get("proof", []):
        if proof not in company.by_proof:
            problems.append(f"{label}: about/proof: нет кейса «{proof}» в профиле компании")
    ids = [stage["id"] for stage in data["stages"]]
    if len(ids) != len(set(ids)):
        problems.append(f"{label}: stages: идентификаторы этапов повторяются")
    if data["status"] == "final":
        if not data.get("next_steps"):
            problems.append(f"{label}: status=final, но не указаны следующие шаги")
        if not data.get("valid_until"):
            problems.append(f"{label}: status=final, но не указан срок действия предложения")
        if not data.get("team"):
            problems.append(f"{label}: status=final, но не указан состав команды")
        priced = [stage for stage in data["stages"] if stage.get("price")]
        if not priced and not data.get("commercials", {}).get("total"):
            problems.append(f"{label}: status=final, но нигде нет стоимости")
        for stage in data["stages"]:
            if not stage.get("gate"):
                problems.append(
                    f"{label}: stages/{stage['id']}: для final нужно условие перехода (gate)"
                )
    return problems
