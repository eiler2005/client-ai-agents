"""Коммерческое предложение: разделы, книга и сборка PDF.

КП собирается из двух источников и ниоткуда больше. Про клиента и работы — файл
предложения в `proposals/`. Про Синимекс — профиль `src/content/company.yaml`, где у
каждой цифры есть источник и дата. Поэтому раздел «О компании» нельзя дописать
«от себя»: услуга, кейс или факт, которых нет в профиле, не пройдут проверку.

Если предложение ссылается на оценку (`project.assessment`), раздел «Понимание задачи»
берёт из неё решение, пробелы и первые шаги плана: заказчику видно, что КП выросло из
обследования, а не из прайс-листа.

Цифры эффекта из профиля печатаются только вместе с оговоркой `caveat`. Это не
юридическая предосторожность, а практическая: обещание чужого результата — самый
быстрый способ испортить второй проект после удачного первого.
"""

from __future__ import annotations

from pathlib import Path

from .content import CONTENT, Company, Proposal
from .pdf import Book, check_glyphs, prepare_assets, rasterise, write_book
from .render import contact_card, heading, table
from .scoring import Result

MODEL = {
    "fixed": "Фиксированная стоимость этапа",
    "tm": "Оплата по фактическим трудозатратам (T&M)",
    "pilot": "Пилот с фиксированной стоимостью и критериями успеха",
    "mixed": "Смешанная модель: фиксированные этапы и T&M на развитие",
}
STATUS = {"draft": "черновик", "review": "на согласовании", "final": "итоговое"}


class ProposalSections:
    """Разделы КП. `figure` решает, как вставлять фигуру: `<picture>` или PNG."""

    def __init__(
        self,
        proposal: Proposal,
        company: Company,
        depth: int,
        figure,
        *,
        assessment: Result | None = None,
    ):
        self.proposal = proposal
        self.company = company
        self.depth = depth
        self.figure = figure
        self.assessment = assessment

    def sub(self, text: str) -> str:
        return heading(self.depth + 1, text)

    def parts(self) -> list[tuple[str, list[str]]]:
        proposal = self.proposal
        return [
            ("Что мы предлагаем", self.summary()),
            ("Понимание задачи", self.understanding()),
            ("Объём работ", self.scope()),
            ("Как мы это делаем", self.approach()),
            ("План работ и сроки", self.plan()),
            *([("Команда", self.team())] if proposal.team else []),
            *([("Риски и как мы их снимаем", self.risks())] if proposal.risks else []),
            *([("Коммерческие условия", self.commercials())] if proposal.commercials else []),
            (f"О компании {self.company.name}", self.about()),
            ("Следующие шаги", self.next_steps()),
        ]

    # --- Резюме ---------------------------------------------------------------

    def summary(self) -> list[str]:
        proposal = self.proposal
        price = proposal.commercials.get("total")
        lines = [
            proposal.project["summary"],
            "",
            self.sub("Коротко"),
        ]
        rows = [
            ["Заказчик", proposal.client_name],
            ["Предмет предложения", proposal.name],
            ["Этапов работ", str(len(proposal.stages))],
            ["Срок", f"{proposal.weeks:g} недель"],
        ]
        if price:
            rows.append(["Стоимость", price])
        if model := proposal.commercials.get("model"):
            rows.append(["Модель работы", MODEL.get(model, model)])
        if proposal.valid_until:
            rows.append(["Предложение действительно до", proposal.valid_until])
        rows.append(["Дата", proposal.date])
        lines += table(["Параметр", "Значение"], rows)
        if proposal.status != "final":
            lines += [
                "",
                "*Предварительная версия предложения: объём и стоимость уточняются после "
                "ответов на открытые вопросы.*",
            ]
        lines += ["", self.sub("Что заказчик получит")]
        for stage in proposal.stages:
            results = "; ".join(stage["deliverables"])
            lines.append(f"- **{stage['name']}** ({stage['weeks']:g} нед.): {results}")
        return lines

    # --- Понимание задачи ------------------------------------------------------

    def understanding(self) -> list[str]:
        context = self.proposal.context
        lines = [context["problem"], "", self.sub("Цели")]
        lines += [f"{index}. {goal}" for index, goal in enumerate(context["goals"], 1)]
        if context.get("metrics"):
            lines += ["", self.sub("По каким числам будем мерить")]
            lines += table(
                ["Метрика", "Сейчас", "Цель", "Примечание"],
                [
                    [
                        metric["name"],
                        metric.get("baseline", "—"),
                        metric.get("target", "—"),
                        metric.get("note", ""),
                    ]
                    for metric in context["metrics"]
                ],
            )
        if self.assessment:
            lines += ["", self.sub("Что показало обследование")]
            result = self.assessment
            lines += [
                f"Оценка проекта от {result.assessment.assessed} по рубрике "
                f"{result.rubric.version}: готовность **{result.overall:.0f} из 100**, "
                f"решение — «{result.verdict['name']}».",
                "",
            ]
            gaps = result.gaps[:4]
            if gaps:
                lines += ["**Пробелы, на закрытие которых направлено предложение:**"]
                lines += [
                    f"- {item.name} — уровень {item.level}. "
                    f"{item.recommendation or item.risk or item.finding}"
                    for item in gaps
                ]
            strengths = result.strengths[:2]
            if strengths:
                lines += ["", "**На что опираемся в работе:**"]
                lines += [f"- {item.name} — уровень {item.level}." for item in strengths]
        return lines

    # --- Объём -----------------------------------------------------------------

    def scope(self) -> list[str]:
        scope = self.proposal.scope
        lines = [self.sub("В объёме работ")]
        lines += [f"- {item}" for item in scope["in"]]
        if scope.get("out"):
            lines += ["", self.sub("Вне объёма работ")]
            lines += [f"- {item}" for item in scope["out"]]
            lines += [
                "",
                "Перечисленное вне объёма может быть добавлено отдельным этапом: мы "
                "выносим это сюда, чтобы граница ответственности была видна до начала работ, "
                "а не обсуждалась в середине.",
            ]
        offerings = [
            self.company.by_offering[item]
            for item in self.proposal.offerings
            if item in self.company.by_offering
        ]
        if offerings:
            lines += ["", self.sub("Какие наши услуги задействованы")]
            lines += table(
                ["Услуга", "Что входит"],
                [[item["name"], item["summary"]] for item in offerings],
            )
        return lines

    # --- Подход ----------------------------------------------------------------

    def approach(self) -> list[str]:
        company = self.company
        lines = [
            "Порядок работы одинаков на всех наших проектах с ИИ-агентами и проверен на "
            "том, что в нём не срабатывает. Сначала разбираем процесс и считаем экономику, "
            "и только потом выбираем технологию: агент применяется там, где он выигрывает "
            "у правил, поиска и обычной автоматизации, а не по умолчанию.",
            "",
            self.sub("Как выбираем и готовим сценарий"),
        ]
        lines += table(
            ["Шаг", "Что делаем"],
            [[item["step"], item["description"]] for item in company.method],
        )
        if company.data.get("method_output"):
            lines += ["", f"**Результат этого разбора:** {company.data['method_output']}"]
        if company.delivery:
            lines += ["", self.sub("Как доводим до промышленной эксплуатации")]
            lines += table(
                ["Этап", "Содержание"],
                [[item["stage"], item["description"]] for item in company.delivery],
            )
        if company.security:
            lines += ["", self.sub("Безопасность и контроль")]
            lines += [f"- {item}" for item in company.security]
        if company.stack:
            lines += ["", self.sub("Технологический контур")]
            lines += table(
                ["Слой", "Что используем"],
                [[layer, ", ".join(items)] for layer, items in company.stack.items()],
            )
        return lines

    # --- План ------------------------------------------------------------------

    def plan(self) -> list[str]:
        proposal = self.proposal
        lines = self.figure(f"timeline.{proposal.id}", "План работ по этапам")
        lines += [""] if lines else []
        lines += table(
            ["Этап", "Срок", "Результат", "Переход дальше"],
            [
                [
                    f"**{stage['name']}**",
                    f"{stage['weeks']:g} нед.",
                    "; ".join(stage["deliverables"]),
                    stage.get("gate", "—"),
                ]
                for stage in proposal.stages
            ],
        )
        for stage in proposal.stages:
            if not stage.get("activities"):
                continue
            lines += ["", self.sub(f"{stage['name']} — {stage['weeks']:g} нед.")]
            if stage.get("goal"):
                lines += [f"**Цель этапа:** {stage['goal']}", ""]
            lines += [f"- {item}" for item in stage["activities"]]
        lines += [
            "",
            f"Суммарный срок — **{proposal.weeks:g} недель** при условии, что доступы и "
            f"ответственные со стороны заказчика выделены к старту этапа.",
        ]
        return lines

    # --- Команда ---------------------------------------------------------------

    def team(self) -> list[str]:
        lines = table(
            ["Роль", "Человек", "Загрузка", "Зона ответственности"],
            [
                [
                    member["role"],
                    f"{member['count']:g}",
                    member.get("load", "—"),
                    member.get("note", "—"),
                ]
                for member in self.proposal.team
            ],
        )
        if self.company.roles:
            lines += [
                "",
                "Мы ведём такие проекты небольшими командами, усиленными агентами. Две "
                "роли в них ключевые.",
                "",
            ]
            for role in self.company.roles:
                lines += [self.sub(role["name"])]
                if role.get("focus"):
                    lines += [f"*{role['focus']}*", ""]
                lines += [role["description"], ""]
        return lines

    # --- Риски -----------------------------------------------------------------

    def risks(self) -> list[str]:
        return [
            "Риски, которые мы видим на старте, и что делаем, чтобы они не сработали.",
            "",
            *table(
                ["Риск", "Что делаем"],
                [[item["title"], item["mitigation"]] for item in self.proposal.risks],
            ),
        ]

    # --- Коммерция -------------------------------------------------------------

    def commercials(self) -> list[str]:
        commercials = self.proposal.commercials
        lines: list[str] = []
        if model := commercials.get("model"):
            lines += [f"**Модель работы:** {MODEL.get(model, model)}", ""]
        priced = [stage for stage in self.proposal.stages if stage.get("price")]
        if priced:
            rows = [[stage["name"], f"{stage['weeks']:g} нед.", stage["price"]] for stage in priced]
            if total := commercials.get("total"):
                rows.append(["**Итого**", f"**{self.proposal.weeks:g} нед.**", f"**{total}**"])
            lines += table(["Этап", "Срок", "Стоимость"], rows)
        elif total := commercials.get("total"):
            lines += [f"**Стоимость работ:** {total}", ""]
        if commercials.get("terms"):
            lines += ["", self.sub("Условия")]
            lines += [f"- {item}" for item in commercials["terms"]]
        if commercials.get("assumptions"):
            lines += ["", self.sub("Допущения, на которых построена оценка")]
            lines += [f"- {item}" for item in commercials["assumptions"]]
            lines += [
                "",
                "Если допущение не подтвердится, мы сообщаем об этом до начала этапа и "
                "пересчитываем срок и стоимость вместе с вами, а не по факту работ.",
            ]
        if self.proposal.valid_until:
            lines += ["", f"Предложение действительно до **{self.proposal.valid_until}**."]
        return lines

    # --- О компании ------------------------------------------------------------

    def about(self) -> list[str]:
        company = self.company
        about = self.proposal.about
        organisation = company.organisation
        lines = [organisation["positioning"], ""]

        chosen = about.get("facts")
        facts = (
            [company.by_fact[item] for item in chosen if item in company.by_fact]
            if chosen
            else company.facts
        )
        if facts:
            lines += [self.sub("Коротко о нас"), ""]
            # Список, а не таблица: блок «о нас» читается как текст, а пустая шапка
            # таблицы в нём выглядит как недозаполненная форма.
            lines += [f"- **{fact['label']}:** {fact['value']}" for fact in facts]

        if about.get("platform", True) and company.platform:
            platform = company.platform
            lines += ["", self.sub(platform["name"]), "", platform["summary"], ""]
            for layer in platform["layers"]:
                lines += [f"**{layer['name']}.** " + "; ".join(layer["items"])]
                lines += [""]

        proof = (
            [company.by_proof[item] for item in about["proof"] if item in company.by_proof]
            if about.get("proof")
            else company.proof_for(self.proposal.industry)
        )
        if proof:
            lines += [self.sub("Что уже сделано")]
            lines += table(
                ["Задача", "Результат"],
                [[item["title"], item["result"]] for item in proof],
            )
            lines += ["", f"*{company.caveat}*"]

        industry = company.industries.get(self.proposal.industry)
        if industry:
            lines += [
                "",
                self.sub(f"Опыт в отрасли: {industry['name'].lower()}"),
                "",
                industry["description"],
            ]

        if about.get("clients", True) and company.clients:
            names = ", ".join(item["name"] for item in company.clients)
            lines += [
                "",
                self.sub("Среди клиентов"),
                "",
                f"{names} и другие организации финансового и промышленного сектора. "
                f"Полный перечень проектов и референсы предоставляем по запросу.",
            ]
        return lines

    # --- Следующие шаги --------------------------------------------------------

    def next_steps(self) -> list[str]:
        steps = self.proposal.next_steps or [
            "Встреча для обсуждения объёма и сроков",
            "Уточнение допущений и согласование плана первого этапа",
        ]
        lines = [f"{index}. {step}" for index, step in enumerate(steps, 1)]
        role = self.proposal.client.get("contact_role")
        lines += [
            "",
            "Готовы обсудить предложение в удобное время"
            + (f" с вами, {role.lower()}, и с командой проекта." if role else " с вашей командой."),
        ]
        if self.company.contacts:
            lines += ["", self.sub("Контакты"), ""]
            lines += contact_card(self.company, depth=self.depth + 2)
        return lines


class ProposalBook(Book):
    """Книга коммерческого предложения."""

    def __init__(
        self,
        proposal: Proposal,
        company: Company,
        assets: Path | None,
        *,
        assessment: Result | None = None,
    ):
        super().__init__(assets)
        self.proposal = proposal
        self.company = company
        self.assessment = assessment
        self.sections = ProposalSections(
            proposal, company, depth=1, figure=self.figure, assessment=assessment
        )

    def cover(self) -> dict:
        proposal = self.proposal
        industry = self.company.industries.get(proposal.industry, {}).get("name", proposal.industry)
        meta = [
            f"<b>Для:</b> {proposal.client_name}"
            + (
                f", {proposal.client['contact_role']}"
                if proposal.client.get("contact_role")
                else ""
            ),
            f"<b>Отрасль:</b> {industry}",
            f"<b>Срок работ:</b> {proposal.weeks:g} недель, этапов — {len(proposal.stages)}",
            *(
                [f"<b>Стоимость:</b> {proposal.commercials['total']}"]
                if proposal.commercials.get("total")
                else []
            ),
            f"<b>Дата:</b> {proposal.date}"
            + (
                f" · <b>действительно до:</b> {proposal.valid_until}"
                if proposal.valid_until
                else ""
            ),
            f"<b>От:</b> {self.company.organisation['legal_name']}",
        ]
        return {
            "title": proposal.name,
            "subtitle": f"Коммерческое предложение · {self.company.name}",
            "meta": meta,
            "notice": (
                "Предложение подготовлено для адресата и содержит коммерческие условия; "
                "распространение за пределы организации заказчика не предполагается."
            ),
        }

    def footer(self) -> str:
        return f"{self.proposal.name} · {self.company.name} · предложение от {self.proposal.date}"

    def content_parts(self) -> list[tuple[str, list[str]]]:
        return self.sections.parts()

    def subject(self) -> dict:
        return {
            "document": "proposal",
            "proposal": self.proposal.id,
            "client": self.proposal.client_name,
            "status": self.proposal.status,
            "assessment": self.proposal.assessment_id,
            "weeks": self.proposal.weeks,
            "stages": len(self.proposal.stages),
            "notes": self.warnings(),
        }

    def inputs(self) -> list[Path]:
        return [CONTENT / "company.yaml", self.proposal.path]

    def warnings(self) -> list[str]:
        """То, что не ломает сборку, но должно попасть на глаза перед отправкой."""
        notes = [
            f"факт «{fact['label']}: {fact['value']}» датирован {fact['as_of']} — подтвердите"
            for fact in self.company.stale_facts()
        ]
        if self.proposal.assessment_id and not self.assessment:
            notes.append(
                f"предложение ссылается на оценку «{self.proposal.assessment_id}», "
                f"но она не найдена: раздел «Что показало обследование» не напечатан"
            )
        if self.proposal.status == "final" and not self.proposal.commercials.get("assumptions"):
            notes.append("итоговое предложение без списка допущений")
        return notes


def prepare_proposal_assets(proposal: Proposal, svg_dir: Path, out: Path) -> Path:
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    rasterise(svg_dir / f"timeline.{proposal.id}.svg", assets / f"timeline.{proposal.id}.png")
    return assets


def file_name(proposal: Proposal) -> str:
    stem = proposal.id if proposal.id.endswith("-kp") else f"{proposal.id}-kp"
    return f"{stem}-{proposal.date}.pdf"


def build(
    proposals: list[Proposal],
    company: Company,
    out: Path,
    svg_dir: Path,
    *,
    assessments: dict[str, Result] | None = None,
    font: str | None = None,
) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    manifests = []
    for proposal in proposals:
        assets = prepare_proposal_assets(proposal, svg_dir, out)
        linked = (assessments or {}).get(proposal.assessment_id or "")
        book = ProposalBook(proposal, company, assets, assessment=linked)
        manifests.append(write_book(book, file_name(proposal), out, font))
    return manifests


__all__ = [
    "ProposalBook",
    "ProposalSections",
    "build",
    "check_glyphs",
    "file_name",
    "prepare_assets",
]
