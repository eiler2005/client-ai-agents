#!/usr/bin/env python3
"""Build an original fictional A4 management example with portable Cinimex tokens."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PACK_DIR = Path(__file__).resolve().parents[1]
TOKEN_PATH = PACK_DIR / "assets" / "design-tokens.json"
FICTION = "ВЫМЫШЛЕННЫЙ ПРИМЕР · ДАННЫЕ ДЛЯ ДЕМОНСТРАЦИИ"
CLAIMS = [
    {
        "id": "Q00",
        "text": "Срез: конец недели 4.",
        "kind": "fictional-as-of",
        "value": 4,
        "unit": "demo-week",
    },
    {
        "id": "Q01",
        "text": "Базовый план проверки завершается в демонстрационную неделю 5.",
        "kind": "fictional-baseline",
        "value": 5,
        "unit": "demo-week",
    },
    {
        "id": "Q02",
        "text": "Текущий прогноз проверки завершается в демонстрационную неделю 6.",
        "kind": "fictional-forecast",
        "value": 6,
        "unit": "demo-week",
    },
    {
        "id": "Q03",
        "text": (
            "Пилот можно начать после проверки источников. Решение сейчас: назначить владельца "
            "данных и согласовать проверку неизвестных случаев."
        ),
        "kind": "fictional-decision",
    },
    {
        "id": "F01",
        "text": "Периметр согласован: один тип внутренних запросов.",
        "kind": "fictional-status",
    },
    {
        "id": "F02",
        "text": "Рабочий сценарий собран; источники проверены частично.",
        "kind": "fictional-status",
    },
    {
        "id": "F03",
        "text": "Риск: нет подтверждённого источника для исключений.",
        "kind": "fictional-risk",
    },
    {
        "id": "F04",
        "text": "Зависимость: владелец данных должен разобрать примеры.",
        "kind": "fictional-dependency",
    },
    {
        "id": "G1",
        "text": "Согласовать периметр",
        "criteria": ["A"],
        "decision_role": "владелец процесса",
        "kind": "fictional-gate",
    },
    {
        "id": "G2",
        "text": "Разрешить сборку",
        "criteria": ["A", "B"],
        "decision_role": "архитектор",
        "kind": "fictional-gate",
    },
    {
        "id": "G3",
        "text": "Решить о расширении",
        "criteria": ["A", "B", "C"],
        "decision_role": "владелец процесса",
        "kind": "fictional-gate",
    },
    {
        "id": "G4",
        "text": "Принять в сопровождение",
        "criteria": ["A", "B", "C", "D"],
        "decision_role": "владелец сервиса",
        "kind": "fictional-gate",
    },
    {
        "id": "W01",
        "text": "Агент готовит ответ; эксперт разбирает пробелы.",
        "kind": "fictional-role-allocation",
    },
    {
        "id": "W02",
        "text": (
            "При отсутствии основания ответ остановлен до подтверждения; "
            "эксперт разбирает неизвестное."
        ),
        "kind": "fictional-exception",
    },
]
CLAIM = {item["id"]: item for item in CLAIMS}
CONTENT = {
    "status": {
        "title": "Пилот можно начать после проверки источников",
        "as_of": CLAIM["Q00"]["text"],
        "decision": (
            "Решение сейчас: назначить владельца данных и согласовать проверку неизвестных случаев."
        ),
        "intro": "Демонстрация для сервиса внутренних запросов. Все статусы и недели вымышлены.",
        "facts": [CLAIM["F01"]["text"], CLAIM["F02"]["text"]],
        "risk_dependency": [CLAIM["F03"]["text"], CLAIM["F04"]["text"]],
        "roadmap_title": "Проверка смещает прогноз; базовый план виден рядом",
        "roadmap": [
            {"activity": "Периметр", "baseline": [1, 2], "forecast": [1, 2]},
            {"activity": "Сборка", "baseline": [2, 4], "forecast": [2, 4]},
            {
                "activity": "Проверка",
                "baseline": [4, CLAIM["Q01"]["value"]],
                "forecast": [4, CLAIM["Q02"]["value"]],
            },
        ],
        "roadmap_caveat": (
            "Все недели и статусы вымышлены. Прогноз показывает зависимость "
            "и не является обязательством по сроку."
        ),
        "recent": "Карта запросов и правила передачи эксперту.",
        "next": "Протокол проверки; решение о старте пилота.",
    },
    "stages": {
        "title": "Каждый этап завершается проверяемым решением",
        "intro": (
            "Сроки, пороги качества и объём пилота требуют отдельного согласования. "
            "Этапы используют одинаковые поля результата, доказательства и роли."
        ),
        "rows": [
            {
                "stage": "01. Обследование",
                "result": "Карта запросов и рамки пилота",
                "evidence": "Примеры сценариев; реестр неизвестного",
                "role": "Владелец процесса",
                "gate": "G1",
            },
            {
                "stage": "02. Проектирование",
                "result": "Путь запроса и правила передачи",
                "evidence": "Матрица ролей; источник для каждого шага",
                "role": "Архитектор + владелец процесса",
                "gate": "G2",
            },
            {
                "stage": "03. Пилот",
                "result": "Рабочий сценарий в ограниченном контуре",
                "evidence": "Протокол испытаний; журнал исключений",
                "role": "Команда пилота + эксперт процесса",
                "gate": "G3",
            },
            {
                "stage": "04. Передача",
                "result": "Регламент работы и поддержка",
                "evidence": "Проверка ответственных; учебный сценарий",
                "role": "Владелец сервиса",
                "gate": "G4",
            },
        ],
        "criteria": {"A": "периметр", "B": "роли и данные", "C": "испытания", "D": "сопровождение"},
        "persistence": (
            "Критерии сохраняются: каждый набор добавляет условие к предыдущему. "
            "Непройденное условие возвращает этап на доработку."
        ),
    },
    "workflow": {
        "title": "Агент готовит ответ; эксперт разбирает пробелы",
        "intro": (
            "Одинаковые шаги показывают изменение ролей. Предлагаемый процесс "
            "сохраняет остановку при отсутствии основания."
        ),
        "rows": [
            {
                "step": "1. Запрос",
                "current_role": "Сотрудник",
                "current": "Передаёт текст запроса эксперту.",
                "proposed_role": "Сотрудник -> агент",
                "proposed": "Уточняет цель и обязательные поля.",
            },
            {
                "step": "2. Основание",
                "current_role": "Эксперт процесса",
                "current": "Ищет источник и проверяет его применимость.",
                "proposed_role": "Агент",
                "proposed": "Находит источник и проверяет его применимость.",
            },
            {
                "step": "3. Подготовка",
                "current_role": "Эксперт процесса",
                "current": "Готовит ответ и вручную разбирает пробелы.",
                "proposed_role": "Агент",
                "proposed": "Готовит проект ответа и прикладывает основание.",
            },
            {
                "step": "4. Результат",
                "current_role": "Сотрудник",
                "current": "Получает ответ после ручной проверки.",
                "proposed_role": "Сотрудник",
                "proposed": "Получает ответ с подтверждённым основанием.",
            },
        ],
        "exception_title": "Нет основания: передать эксперту",
        "exception": CLAIM["W02"]["text"],
        "exception_route": (
            "Ветвь начинается на шаге «Основание». Пока источник не подтверждён, "
            "агент не переходит к подготовке и выдаче ответа."
        ),
        "current_note": "Человек выполняет поиск, проверку и обработку исключений.",
    },
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def gate_text(gate_id: str) -> str:
    gate = CLAIM[gate_id]
    return (
        f"{gate_id}. {gate['text']} - критерии {{{', '.join(gate['criteria'])}}}. "
        f"Решение: {gate['decision_role']}."
    )


def strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for child in value.values() for text in strings(child)]
    if isinstance(value, list):
        return [text for child in value for text in strings(child)]
    return []


def resolve_fonts(font_dir: Path | None, preferred: str) -> dict[str, str]:
    families = [
        ("DejaVu Sans", ["DejaVuSans.ttf"], ["DejaVuSans-Bold.ttf"]),
        ("Calibri", ["Calibri.ttf", "calibri.ttf"], ["Calibri Bold.ttf", "calibrib.ttf"]),
        ("Arial", ["Arial.ttf", "arial.ttf"], ["Arial Bold.ttf", "arialbd.ttf"]),
        ("Liberation Sans", ["LiberationSans-Regular.ttf"], ["LiberationSans-Bold.ttf"]),
        ("Noto Sans", ["NotoSans-Regular.ttf"], ["NotoSans-Bold.ttf"]),
    ]
    families.sort(key=lambda family: family[0] != preferred)
    common = [
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
        Path.home() / "Library" / "Fonts",
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
    ]
    groups = [[font_dir]] if font_dir else []
    groups.append(common)
    for directories in groups:
        index = {}
        for directory in directories:
            if directory and directory.is_dir():
                for file in sorted(directory.rglob("*")):
                    if file.is_file() and file.suffix.lower() == ".ttf":
                        index.setdefault(file.name.lower(), file)
        for family, regular_names, bold_names in families:
            regular = next(
                (index[name.lower()] for name in regular_names if name.lower() in index), None
            )
            bold = next((index[name.lower()] for name in bold_names if name.lower() in index), None)
            if regular and bold:
                return {"family": family, "regular": str(regular), "bold": str(bold)}
    raise RuntimeError(
        "No compatible Cyrillic regular/bold font pair found. Provide --font-dir with "
        "DejaVuSans.ttf and DejaVuSans-Bold.ttf or another supported family."
    )


def register_fonts(fonts: dict[str, str], copy: list[str]) -> None:
    for alias, key in [("CinimexRegular", "regular"), ("CinimexBold", "bold")]:
        font = TTFont(alias, fonts[key])
        pdfmetrics.registerFont(font)
        missing = sorted(
            {character for text in copy for character in text if not character.isspace()}
            - set(map(chr, font.face.charToGlyph))
        )
        if missing:
            codes = ", ".join(f"{character!r} U+{ord(character):04X}" for character in missing)
            raise RuntimeError(f"Font {fonts[key]} lacks required glyphs: {codes}")
    pdfmetrics.registerFontFamily(
        "CinimexRegular", normal="CinimexRegular", bold="CinimexBold", italic="CinimexRegular"
    )


class Roadmap(Flowable):
    """Native PDF vectors with one six-week axis for baseline and forecast."""

    def __init__(self, width: float, tokens: dict, expected: list[str]):
        super().__init__()
        self.width, self.height = width, 144
        self.tokens, self.expected = tokens, expected

    def draw(self) -> None:
        canvas = self.canv
        palette, doc = self.tokens["colors"], self.tokens["document"]
        left, right = 112, self.width - 10
        week_count = max(CLAIM["Q01"]["value"], CLAIM["Q02"]["value"])

        def tick(week):
            return left + (week - 1) * (right - left) / (week_count - 1)

        canvas.setFont("CinimexRegular", doc["body"])
        for label, color, x in [
            ("Базовый", palette["baseline"], 0),
            ("Прогноз", palette["orange"], 150),
        ]:
            canvas.setFillColor(colors.HexColor(color))
            canvas.rect(x, 131, 16, 4, fill=1, stroke=0)
            canvas.setFillColor(colors.HexColor(palette["navy"]))
            canvas.drawString(x + 23, 128, label)
            self.expected.append(label)
        canvas.setStrokeColor(colors.HexColor(palette["grid"]))
        canvas.setLineWidth(0.5)
        canvas.line(left, 100, right, 100)
        canvas.setFont("CinimexRegular", doc["source"])
        for week in range(1, week_count + 1):
            x = tick(week)
            canvas.line(x, 12, x, 100)
            canvas.setFillColor(colors.HexColor(palette["muted"]))
            label = f"Нед. {week}"
            canvas.drawCentredString(x, 109, label)
            self.expected.append(label)
        for item, y in zip(CONTENT["status"]["roadmap"], [78, 49, 20], strict=True):
            canvas.setFont("CinimexBold", doc["body"])
            canvas.setFillColor(colors.HexColor(palette["navy"]))
            canvas.drawString(0, y, item["activity"])
            self.expected.append(item["activity"])
            for kind, color, offset in [
                ("baseline", palette["baseline"], 4),
                ("forecast", palette["orange"], -5),
            ]:
                start, end = item[kind]
                canvas.setFillColor(colors.HexColor(color))
                canvas.rect(tick(start), y + offset, tick(end) - tick(start), 4, fill=1, stroke=0)


def markdown() -> str:
    status, stages, workflow = (CONTENT[key] for key in ["status", "stages", "workflow"])
    lines = [
        f"> {FICTION}",
        "",
        f"# {status['title']}",
        "",
        status["decision"],
        "",
        status["as_of"],
        "",
        status["intro"],
        "",
    ]
    lines += ["<!-- claims: Q00 Q03 F01 F02 F03 F04 -->", "", "## Что известно", ""]
    lines += [f"- {fact}" for fact in status["facts"]]
    lines += ["", "## Риск и зависимость", ""]
    lines += [f"- {fact}" for fact in status["risk_dependency"]]
    lines += ["", f"## {status['roadmap_title']}", "", "<!-- claims: Q01 Q02 -->", ""]
    lines += [
        "| Работа | Базовый план, демо-недели | Текущий прогноз, демо-недели |",
        "|---|---|---|",
    ]
    lines += [
        f"| {item['activity']} | {item['baseline'][0]}-{item['baseline'][1]} | "
        f"{item['forecast'][0]}-{item['forecast'][1]} |"
        for item in status["roadmap"]
    ]
    lines += [
        "",
        status["roadmap_caveat"],
        "",
        "## Недавно получено",
        "",
        status["recent"],
        "",
        "## Следующий результат",
        "",
        status["next"],
        "",
    ]
    lines += [
        "<!-- pagebreak -->",
        "",
        f"# {stages['title']}",
        "",
        stages["intro"],
        "",
        "<!-- claims: G1 G2 G3 G4 -->",
        "",
    ]
    lines += ["| Этап | Результат | Доказательство | Ответственная роль |", "|---|---|---|---|"]
    for row in stages["rows"]:
        lines += [
            f"| {row['stage']} | {row['result']} | {row['evidence']} | {row['role']} |",
            f"| **{gate_text(row['gate'])}** | | | |",
        ]
    lines += ["", "## Накопление критериев", ""]
    lines += [f"- {key} - {value}." for key, value in stages["criteria"].items()]
    lines += [
        "",
        stages["persistence"],
        "",
        "<!-- pagebreak -->",
        "",
        f"# {workflow['title']}",
        "",
        workflow["intro"],
        "",
        "<!-- claims: W01 W02 -->",
        "",
    ]
    lines += ["| Шаг | Текущий процесс - демо | Предлагаемый процесс - демо |", "|---|---|---|"]
    for row in workflow["rows"]:
        lines += [
            f"| {row['step']} | **{row['current_role']}**: {row['current']} | "
            f"**{row['proposed_role']}**: {row['proposed']} |"
        ]
    lines += [
        "",
        f"## {workflow['exception_title']}",
        "",
        workflow["exception"],
        "",
        workflow["exception_route"],
        "",
        workflow["current_note"],
        "",
    ]
    lines += [
        "Источник: оригинальный вымышленный сценарий. Пример не подтверждает готовность, "
        "сроки или бизнес-эффект реального проекта.",
        "",
    ]
    lines += ["<!-- claim ledger: " + json.dumps(CLAIMS, ensure_ascii=False) + " -->", ""]
    return "\n".join(lines)


def build_pdf(out: Path, tokens: dict, expected: list[str]) -> Path:
    doc = tokens["document"]
    palette = {key: colors.HexColor(value) for key, value in tokens["colors"].items()}
    margin = doc["margin"]
    page_width, page_height = A4
    width = page_width - 2 * margin
    styles = {
        "body": ParagraphStyle(
            "Body",
            fontName="CinimexRegular",
            fontSize=doc["body"],
            leading=doc["leading"],
            textColor=palette["navy"],
            spaceAfter=7,
        ),
        "title": ParagraphStyle(
            "Title",
            fontName="CinimexBold",
            fontSize=doc["title"],
            leading=doc["title"] * 1.22,
            textColor=palette["navy"],
            spaceAfter=13,
        ),
        "heading": ParagraphStyle(
            "Heading",
            fontName="CinimexBold",
            fontSize=doc["heading"],
            leading=doc["heading"] * 1.25,
            textColor=palette["navy"],
            spaceBefore=8,
            spaceAfter=9,
        ),
        "decision": ParagraphStyle(
            "Decision",
            fontName="CinimexBold",
            fontSize=doc["body"],
            leading=doc["leading"],
            textColor=palette["accentText"],
            spaceAfter=13,
        ),
        "cell": ParagraphStyle(
            "Cell",
            fontName="CinimexRegular",
            fontSize=doc["body"],
            leading=doc["leading"],
            textColor=palette["navy"],
        ),
        "cell_header": ParagraphStyle(
            "CellHeader",
            fontName="CinimexBold",
            fontSize=doc["body"],
            leading=doc["leading"],
            textColor=palette["white"],
        ),
        "muted": ParagraphStyle(
            "Muted",
            fontName="CinimexRegular",
            fontSize=doc["body"],
            leading=doc["leading"],
            textColor=palette["muted"],
            spaceAfter=7,
        ),
    }

    def paragraph(copy: str, style: str = "body", bold_lead: str | None = None) -> Paragraph:
        expected.append(f"{bold_lead} {copy}" if bold_lead else copy)
        value = f"<b>{escape(bold_lead)}</b><br/>{escape(copy)}" if bold_lead else escape(copy)
        return Paragraph(value, styles[style])

    def standard_table(values: list[list], widths: list[float], header: bool = True) -> Table:
        if len(widths) > doc["maxTableColumns"]:
            raise ValueError("Table exceeds the document token column limit")
        table = Table(values, colWidths=widths, hAlign="LEFT", repeatRows=1 if header else 0)
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.45, palette["grid"]),
                ]
            )
        )
        if header:
            table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), palette["navy"])]))
        return table

    def chrome(canvas, pdf_doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(palette["navy"])
        canvas.setLineWidth(1.2)
        canvas.line(margin, page_height - 31, page_width - margin, page_height - 31)
        canvas.setStrokeColor(palette["orange"])
        canvas.line(margin, page_height - 31, margin + 42, page_height - 31)
        canvas.setFillColor(palette["muted"])
        canvas.setFont("CinimexRegular", doc["source"])
        canvas.drawString(margin, page_height - 47, FICTION)
        canvas.drawString(margin, 26, "Синимекс | Источник: оригинальный вымышленный сценарий")
        canvas.drawRightString(page_width - margin, 26, str(pdf_doc.page))
        canvas.restoreState()

    story = []
    status = CONTENT["status"]
    story.extend(
        [
            paragraph(status["title"], "title"),
            paragraph(status["decision"], "decision"),
            paragraph(status["as_of"], "muted"),
            paragraph(status["intro"], "muted"),
        ]
    )
    status_columns = [
        [
            [paragraph("Что известно", "heading"), *[paragraph(fact) for fact in status["facts"]]],
            [
                paragraph("Риск и зависимость", "heading"),
                *[paragraph(fact) for fact in status["risk_dependency"]],
            ],
        ]
    ]
    status_table = standard_table(status_columns, [width * 0.49, width * 0.51], header=False)
    story.extend(
        [
            status_table,
            Spacer(1, 6),
            paragraph(status["roadmap_title"], "heading"),
            Roadmap(width, tokens, expected),
            paragraph(status["roadmap_caveat"], "muted"),
        ]
    )
    results = [
        [
            [paragraph("Недавно получено", "heading"), paragraph(status["recent"])],
            [paragraph("Следующий результат", "heading"), paragraph(status["next"])],
        ]
    ]
    story.extend([standard_table(results, [width * 0.49, width * 0.51], header=False), PageBreak()])

    stages = CONTENT["stages"]
    story.extend(
        [
            paragraph(stages["title"], "title"),
            paragraph(stages["intro"], "muted"),
            Spacer(1, 7),
        ]
    )
    rows = [
        [
            paragraph(copy, "cell_header")
            for copy in ["Этап", "Результат", "Доказательство", "Ответственная роль"]
        ]
    ]
    for row in stages["rows"]:
        rows.append(
            [paragraph(row[key], "cell") for key in ["stage", "result", "evidence", "role"]]
        )
        rows.append([paragraph(gate_text(row["gate"]), "decision"), "", "", ""])
    stage_table = standard_table(rows, [width * 0.22, width * 0.24, width * 0.29, width * 0.25])
    gate_commands = []
    for row in range(2, 9, 2):
        gate_commands += [
            ("SPAN", (0, row), (-1, row)),
            ("LINEABOVE", (0, row), (-1, row), 0.8, palette["orange"]),
            ("TOPPADDING", (0, row), (-1, row), 5),
            ("BOTTOMPADDING", (0, row), (-1, row), 5),
        ]
    for row in [3, 7]:
        gate_commands.append(("BACKGROUND", (0, row), (-1, row), palette["paper"]))
    stage_table.setStyle(TableStyle(gate_commands))
    story.extend([stage_table, Spacer(1, 11), paragraph("Накопление критериев", "heading")])
    criteria = " · ".join(f"{key} - {value}" for key, value in stages["criteria"].items())
    story.extend([paragraph(criteria), paragraph(stages["persistence"], "muted"), PageBreak()])

    workflow = CONTENT["workflow"]
    story.extend(
        [
            paragraph(workflow["title"], "title"),
            paragraph(workflow["intro"], "muted"),
            Spacer(1, 7),
        ]
    )
    rows = [
        [
            paragraph(copy, "cell_header")
            for copy in ["Шаг", "Текущий процесс - демо", "Предлагаемый процесс - демо"]
        ]
    ]
    for row in workflow["rows"]:
        rows.append(
            [
                paragraph(row["step"], "cell"),
                paragraph(row["current"], "cell", row["current_role"]),
                paragraph(row["proposed"], "cell", row["proposed_role"]),
            ]
        )
    story.extend(
        [
            standard_table(rows, [width * 0.17, width * 0.415, width * 0.415]),
            Spacer(1, 14),
        ]
    )
    story.append(
        KeepTogether(
            [
                paragraph(workflow["exception_title"], "heading"),
                paragraph(workflow["exception"], "decision"),
                paragraph(workflow["exception_route"]),
                paragraph(workflow["current_note"], "muted"),
            ]
        )
    )
    pdf = out / "consulting-document-example.pdf"
    pdf_doc = SimpleDocTemplate(
        str(pdf),
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=68,
        bottomMargin=45,
        title="Сервис внутренних запросов - вымышленный пример",
        author="Синимекс",
        subject="Оригинальная демонстрация решений, этапов и ролей",
    )
    pdf_doc.build(story, onFirstPage=chrome, onLaterPages=chrome)
    return pdf


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("output/consulting-document-example"))
    parser.add_argument(
        "--font-dir", type=Path, help="Directory containing Cyrillic regular/bold TTF fonts"
    )
    args = parser.parse_args()
    tokens = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    doc = tokens["document"]
    if doc["page"] != "A4" or doc["orientation"] != "portrait" or doc["unit"] != "pt":
        raise ValueError("This document example requires A4 portrait document tokens in points")
    fonts = resolve_fonts(args.font_dir, doc["font"])
    copy = strings(CONTENT) + strings(CLAIMS) + [FICTION]
    copy += [gate_text(gate) for gate in ["G1", "G2", "G3", "G4"]]
    copy += [
        "Синимекс | Источник: оригинальный вымышленный сценарий",
        "0123456789",
        "Базовый",
        "Прогноз",
        "Нед.",
        "Что известно",
        "Риск и зависимость",
        "Недавно получено",
        "Следующий результат",
        "Накопление критериев",
        "Этап",
        "Результат",
        "Доказательство",
        "Ответственная роль",
        "Шаг",
        "Текущий процесс - демо",
        "Предлагаемый процесс - демо",
    ]
    register_fonts(fonts, copy)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    expected = []
    pdf = build_pdf(out, tokens, expected)
    md = out / "consulting-document-example.md"
    md.write_text(markdown(), encoding="utf-8")
    source = out / "consulting-document-example.source.json"
    source.write_text(
        json.dumps({"claims": CLAIMS, "content": CONTENT}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    reader = PdfReader(pdf)
    if len(reader.pages) != 3:
        raise RuntimeError(
            f"Expected 3 A4 pages; got {len(reader.pages)}. Revise the layout before handoff."
        )
    extracted_pages = [page.extract_text() or "" for page in reader.pages]
    extracted = "\n\n".join(
        f"PAGE {index + 1}\n{copy}" for index, copy in enumerate(extracted_pages)
    )
    missing = [copy for copy in expected if normalize(copy) not in normalize(extracted)]
    if missing:
        raise RuntimeError("PDF lost source copy: " + "; ".join(missing))
    if "\ufffd" in extracted:
        raise RuntimeError("PDF text contains an unresolved replacement character")
    image_count = sum(len(page.images) for page in reader.pages)
    if image_count:
        raise RuntimeError(
            "The document example must contain native text/vector objects, not images"
        )
    text = out / "consulting-document-example.text.txt"
    ledger = "\n".join(f"[{claim['id']}] {claim['text']}" for claim in CLAIMS)
    text.write_text(
        f"CLAIM LEDGER (FICTIONAL SOURCE)\n{ledger}\n\nEXTRACTED PDF COPY\n{extracted}\n",
        encoding="utf-8",
    )
    preview = out / "preview"
    preview.mkdir(exist_ok=True)
    renderer = shutil.which("pdftoppm")
    previews = []
    if renderer:
        subprocess.run(
            [renderer, "-r", "144", "-png", str(pdf), str(preview / "page")],
            check=True,
            capture_output=True,
            text=True,
        )
        previews = sorted(preview.glob("page-*.png"))
        if len(previews) != len(reader.pages):
            raise RuntimeError("Rendered preview count differs from the PDF page count")
    files = [pdf, md, source, text, *previews]
    manifest = {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "state": "draft",
        "purpose": "original-fictional-A4-document",
        "generator": {
            "script": "scripts/render_document_example.py",
            "tokens": "assets/design-tokens.json",
            "tokens_version": tokens["version"],
        },
        "source": {
            "kind": "original-fictional-examples",
            "client_files_used": False,
            "external_sources": [],
            "content_source": str(source),
        },
        "claims": CLAIMS,
        "style": {
            "tokens": doc,
            "palette": tokens["colors"],
            "font_requested": doc["font"],
            "font_resolved": fonts,
            "font_fallback": fonts["family"] != doc["font"],
        },
        "output": {
            "pdf": str(pdf),
            "markdown": str(md),
            "source": str(source),
            "text": str(text),
            "previews": [str(file) for file in previews],
        },
        "checks": {
            "page_count": 3,
            "pdf_verified_independently": True,
            "expected_copy_verified_from_pdf": True,
            "missing_copy": [],
            "font_glyphs_checked": True,
            "native_text_and_vectors": True,
            "images": image_count,
            "all_pages_rendered": len(previews) == 3,
            "visual_review": False,
            "visual_review_note": (
                "Inspect every final page PNG and record actual review separately."
            ),
            "no_roi_or_acceptance_claims": True,
        },
        "sha256": {
            str(file.relative_to(out)): hashlib.sha256(file.read_bytes()).hexdigest()
            for file in files
        },
        "limitations": [
            "Fictional examples establish no actual project readiness, quality threshold, "
            "schedule or business effect.",
            "PDF is native text/vector output; there is no DOCX output "
            "or PowerPoint-to-PDF conversion.",
            "Font resolution may use a documented Cyrillic fallback "
            "when the preferred family is unavailable.",
            "Generation and rendering do not establish visual approval.",
        ],
    }
    manifest_path = out / "consulting-document-example.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "pdf": str(pdf),
                "markdown": str(md),
                "manifest": str(manifest_path),
                "previews": [str(file) for file in previews],
                "pages": len(reader.pages),
                "font": fonts["family"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
