"""Сборка документа клиенту в PDF: титул, оглавление с настоящими номерами страниц, части.

Здесь живёт общий механизм печати. Отчёт по оценке собирает `AssessmentBook`,
коммерческое предложение — `ProposalBook` в `proposal.py`; оба наследуют `Book` и
отличаются только титулом, колонтитулом и набором частей.

Оглавление не угадывает страницы. Книга печатается, из закладок готового файла
читаются номера страниц частей, оглавление пересобирается с ними и книга печатается
снова — пока номера не совпадут с тем, что получилось. В выдаваемых байтах номера верны,
а не «почти верны».

Шрифт проверяется до печати: символ, которого в шрифте нет, в PDF превращается в пустой
квадрат, и в документе для заказчика это недопустимо. Сборка падает с перечнем символов.

Рядом с PDF пишется манифест: контрольные суммы входных файлов, шрифтов и фигур, число
страниц и sha256 самого файла. По нему через полгода можно сказать, из чего собран
именно тот файл, который ушёл заказчику.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import pdf_render
from .content import CONTENT, ContentError, Rubric, load_assessments, load_rubric
from .pdf_render import PAGEBREAK, digest, font_files, missing_glyphs
from .render import Sections, plain_image, table
from .scoring import Result, score

FONT_SIZE = 11
PLACEHOLDER = "000"
# Символы, которые аналитик пишет не задумываясь, а системного шрифта для них нет.
# Замена делается до проверки глифов и только для этого короткого списка: всё
# остальное, чего в шрифте не нашлось, валит сборку, а не печатается пустым квадратом.
SUBSTITUTE = {"₽": "руб.", "₸": "тенге", "₴": "грн.", " ": " ", " ": " "}
NOTICE = "Конфиденциально. Подготовлено для внутреннего использования заказчика."
MAX_PASSES = 5


def substitute(text: str) -> str:
    for original, replacement in SUBSTITUTE.items():
        text = text.replace(original, replacement)
    return text


class Book:
    """Основа документа: титул, оглавление и части, каждая со своим H1.

    Наследник отвечает за три вещи — титул, колонтитул и список частей. Всё
    остальное (оглавление с настоящими номерами, разрывы страниц, подстановка
    символов, подсчёт частей) одинаково для отчёта и для предложения.
    """

    def __init__(self, assets: Path | None):
        self.assets = assets

    def figure(self, name: str, caption: str) -> list[str]:
        """Фигура попадает в книгу только если её PNG действительно лежит рядом."""
        if self.assets and (self.assets / f"{name}.png").is_file():
            return plain_image(name, caption)
        return []

    def cover(self) -> dict:
        raise NotImplementedError

    def footer(self) -> str:
        raise NotImplementedError

    def content_parts(self) -> list[tuple[str, list[str]]]:
        raise NotImplementedError

    def subject(self) -> dict:
        """Поля для манифеста, описывающие, о чём этот документ."""
        raise NotImplementedError

    def inputs(self) -> list[Path]:
        """Файлы, из которых собран документ: их контрольные суммы идут в манифест."""
        return []

    def printed_cover(self) -> dict:
        """Титул с той же подстановкой символов, что и остальной текст книги."""
        cover = self.cover()
        return {
            "title": substitute(cover["title"]),
            "subtitle": substitute(cover["subtitle"]),
            "meta": [substitute(line) for line in cover["meta"]],
            "notice": substitute(cover["notice"]),
        }

    def cover_text(self) -> str:
        """Весь текст титула одной строкой — для проверки глифов."""
        cover = self.printed_cover()
        return "\n".join([cover["title"], cover["subtitle"], *cover["meta"], cover["notice"]])

    def contents(self, pages: list[int] | None) -> list[str]:
        titles = [title for title, _ in self.content_parts()]
        numbers = pages or [None] * len(titles)
        rows = [
            [title, str(number) if number is not None else PLACEHOLDER]
            for title, number in zip(titles, numbers, strict=True)
        ]
        return table(["Раздел", "Стр."], rows)

    def markdown(self, pages: list[int] | None = None) -> str:
        parts = [("Содержание", self.contents(pages)), *self.content_parts()]
        lines: list[str] = []
        for index, (title, body) in enumerate(parts):
            if index:
                # Пустая строка обязательна: без неё маркер разрыва прилипает к
                # предыдущей таблице и печатается её последней строкой.
                lines += ["", PAGEBREAK, ""]
            lines += [f"# {title}", "", *body]
        return substitute("\n".join(lines) + "\n")

    def part_count(self) -> int:
        return len(self.content_parts()) + 1  # плюс оглавление


class AssessmentBook(Book):
    """Отчёт по оценке проекта."""

    def __init__(self, result: Result, assets: Path | None, *, brief: bool = False):
        super().__init__(assets)
        self.result = result
        self.assessment = result.assessment
        self.brief = brief
        self.sections = Sections(result, depth=1, figure=self.figure, detail=not brief)

    @property
    def title(self) -> str:
        suffix = " — краткая версия" if self.brief else ""
        return f"Оценка проекта ИИ-агента{suffix}"

    def subject(self) -> dict:
        return {
            "assessment": self.assessment.id,
            "client": self.assessment.client,
            "status": self.assessment.status,
            "kind": "brief" if self.brief else "full",
            "verdict": self.result.verdict["id"],
            "overall": round(self.result.overall, 1),
            "notes": self.result.notes,
        }

    def inputs(self) -> list[Path]:
        return [CONTENT / "rubric.yaml", CONTENT / "company.yaml", self.assessment.path]

    def cover(self) -> dict:
        project = self.assessment.project
        rubric = self.result.rubric
        stage = rubric.stages.get(project["stage"], {}).get("name", project["stage"])
        pattern = rubric.patterns.get(project["pattern"], {}).get("name", project["pattern"])
        meta = [
            f"<b>Заказчик:</b> {self.assessment.client}",
            f"<b>Стадия:</b> {stage} · <b>Тип решения:</b> {pattern}",
            f"<b>Решение:</b> {self.result.verdict['name']} · "
            f"<b>Готовность:</b> {self.result.overall:.0f} из 100",
            f"<b>Дата оценки:</b> {self.assessment.assessed}",
            f"<b>Оценку проводили:</b> {', '.join(project.get('assessors', [])) or '—'}",
            f"<b>Рубрика:</b> версия {rubric.version} от {rubric.updated}",
        ]
        return {
            "title": self.assessment.name,
            "subtitle": self.title,
            "meta": meta,
            "notice": NOTICE,
        }

    def footer(self) -> str:
        return f"{self.assessment.name} · {self.assessment.client} · Конфиденциально"

    def content_parts(self) -> list[tuple[str, list[str]]]:
        parts = self.sections.parts()
        if self.brief:
            keep = {
                "Резюме для руководства",
                "Оценка по измерениям",
                "Риски",
                "План 30/60/90",
                "Контакты",
            }
            parts = [part for part in parts if part[0] in keep]
        return parts


def rasterise(svg: Path, png: Path, zoom: int = 2) -> bool:
    """SVG → PNG через rsvg-convert. Без него книга печатается без фигур."""
    tool = shutil.which("rsvg-convert")
    if not tool or not svg.is_file():
        return False
    png.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [tool, "--zoom", str(zoom), "--format", "png", "--output", str(png), str(svg)],
        check=True,
    )
    return True


def prepare_assets(result: Result, svg_dir: Path, out: Path) -> Path:
    """Готовит каталог PNG рядом с книгой; возвращает его, даже если он пуст."""
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    names = [f"scorecard.{result.assessment.id}", f"radar.{result.assessment.id}"]
    if result.assessment.risks:
        names.append(f"risks.{result.assessment.id}")
    for name in names:
        rasterise(svg_dir / f"{name}.svg", assets / f"{name}.png")
    return assets


def render_book(book: Book, font: str | None) -> tuple[bytes, str, dict[str, str], list[int]]:
    """Печатает книгу, пока номера в оглавлении не совпадут с закладками файла."""
    pages: list[int] | None = None
    for _ in range(MAX_PASSES):
        markdown = book.markdown(pages)
        resources: dict[str, str] = {}
        data = pdf_render.render_markdown(
            markdown,
            cover=book.printed_cover(),
            footer=substitute(book.footer()),
            font_path=font,
            font_size=FONT_SIZE,
            source_dir=book.assets,
            resource_root=book.assets,
            resources=resources,
        )
        found = pdf_render.part_pages(data)
        if len(found) != book.part_count():
            raise SystemExit(
                f"В книге {len(found)} верхних заголовков вместо {book.part_count()}: "
                f"у каждой части должен быть ровно один H1"
            )
        if found[1:] == pages:
            return data, markdown, resources, pages
        pages = found[1:]
    raise SystemExit("Номера страниц в оглавлении не сошлись за отведённые проходы")


def check_glyphs(markdown: str, font: str | None) -> None:
    regular, bold = font_files(font)
    missing = set(missing_glyphs(markdown, regular)) | set(missing_glyphs(markdown, bold))
    if missing:
        raise SystemExit("В шрифте нет глифов для символов: " + " ".join(sorted(missing)))


def write_book(book: Book, name: str, out: Path, font: str | None) -> dict:
    """Печатает одну книгу, кладёт рядом её Markdown и манифест, возвращает манифест."""
    check_glyphs(book.markdown() + "\n" + book.cover_text(), font)
    data, markdown, resources, pages = render_book(book, font)
    regular, bold = font_files(font)
    (out / name).write_bytes(data)
    (out / f"{name}.md").write_text(markdown, encoding="utf-8")
    text = pdf_render.extract_text(data)
    subject = book.subject()
    notes = subject.pop("notes", [])
    manifest = {
        "output": name,
        **subject,
        "font_size": FONT_SIZE,
        "fonts": {
            "regular": {"path": str(regular), "sha256": digest(regular.read_bytes())},
            "bold": {"path": str(bold), "sha256": digest(bold.read_bytes())},
        },
        "renderer": {
            "module": "assess.pdf_render",
            "sha256": digest(Path(pdf_render.__file__).read_bytes()),
        },
        "markdown_sha256": digest(markdown.encode("utf-8")),
        "resources": resources,
        "contents": [
            {"part": title, "page": page}
            for (title, _), page in zip(book.content_parts(), pages or [], strict=False)
        ],
        "inputs": {path.name: digest(path.read_bytes()) for path in book.inputs()},
        "checks": {
            # Заглушку ищем в самом оглавлении, а не в тексте: «000» встречается в
            # любой цене и в тексте страницы ничего не значит.
            "placeholder_left": PLACEHOLDER in "\n".join(book.contents(pages)),
            "confidentiality_notice": NOTICE.split(".")[0] in text,
            "notes": notes,
        },
        **pdf_render.inspect_pdf(data),
    }
    (out / f"{name}.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def file_name(result: Result, brief: bool) -> str:
    kind = "brief" if brief else "report"
    return f"{result.assessment.id}-{kind}-{result.assessment.assessed}.pdf"


def build(
    results: list[Result],
    out: Path,
    svg_dir: Path,
    *,
    brief: bool = False,
    font: str | None = None,
) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    manifests = []
    for result in results:
        assets = prepare_assets(result, svg_dir, out)
        book = AssessmentBook(result, assets, brief=brief)
        manifests.append(write_book(book, file_name(result, brief), out, font))
    return manifests


def report_line(out: Path, manifest: dict) -> str:
    """Одна строка о напечатанном файле: что получилось и на что посмотреть."""
    flags = ""
    if manifest["checks"]["placeholder_left"]:
        flags += " ВНИМАНИЕ: остались заглушки номеров"
    if manifest["checks"]["notes"]:
        flags += f" · замечаний: {len(manifest['checks']['notes'])}"
    return (
        f"{out / manifest['output']}: {manifest['pages']} стр., "
        f"sha256 {manifest['sha256'][:12]}…{flags}"
    )


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Печать отчётов по оценкам в PDF")
    parser.add_argument("--input", type=Path, default=root / "assessments")
    parser.add_argument("--out", type=Path, default=root / "dist" / "pdf")
    parser.add_argument(
        "--assets",
        type=Path,
        default=root / "docs" / "assets",
        help="каталог SVG-фигур; соберите их через `assess build`",
    )
    parser.add_argument("--only", help="идентификатор одной оценки")
    parser.add_argument("--brief", action="store_true", help="краткая версия без разбора измерений")
    parser.add_argument("--font", help="путь к Unicode TTF; по умолчанию системный")
    args = parser.parse_args(argv)

    try:
        rubric: Rubric = load_rubric()
        assessments = load_assessments(args.input, rubric)
    except ContentError as error:
        print(f"Проблемы в содержимом ({len(error.problems)}):", file=sys.stderr)
        for problem in error.problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    if args.only:
        assessments = [item for item in assessments if item.id == args.only]
        if not assessments:
            print(f"Оценка «{args.only}» не найдена в {args.input}", file=sys.stderr)
            return 1
    results = [score(item, rubric) for item in assessments]
    manifests = build(
        results,
        args.out.resolve(),
        args.assets.resolve(),
        brief=args.brief,
        font=args.font,
    )
    for manifest in manifests:
        print(report_line(args.out, manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
