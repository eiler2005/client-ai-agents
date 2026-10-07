"""Командная строка: `check`, `score`, `build`, `pdf`, `proposal`, `company`, `new`.

Порядок работы на проекте: `new` создаёт файл оценки или предложения из шаблона,
`check` держит его в форме, пока он заполняется, `score` показывает балл в терминале,
`build` собирает фигуры и страницы, `pdf` печатает отчёт, `proposal` — КП.

Флаг `--demo` переключает все пути на вымышленные примеры из `examples/`: ими удобно
проверять сборку, не доставая данные клиентов.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from . import charts, deck, pdf, proposal, render, slides
from .content import (
    Company,
    ContentError,
    Proposal,
    load_assessments,
    load_company,
    load_proposals,
    load_rubric,
)
from .scoring import Result, portfolio, score

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
DEMO = ROOT / "examples"


def report_problems(error: ContentError) -> int:
    print(f"Проблемы в содержимом ({len(error.problems)}):", file=sys.stderr)
    for problem in error.problems:
        print(f"- {problem}", file=sys.stderr)
    return 1


def paths(args) -> tuple[Path, Path]:
    """Каталоги оценок и предложений с учётом `--demo`."""
    if args.demo:
        return DEMO / "assessments", DEMO / "proposals"
    return args.input, args.proposals


def load_results(where: Path) -> list[Result]:
    rubric = load_rubric()
    if where.is_dir() and not any(where.glob("*.yaml")):
        return []
    return [score(item, rubric) for item in load_assessments(where, rubric)]


def load_offers(where: Path, company: Company) -> list[Proposal]:
    if where.is_dir() and not any(where.glob("*.yaml")):
        return []
    if not where.exists():
        return []
    return load_proposals(where, company)


def linked_assessments(results: list[Result]) -> dict[str, Result]:
    return {item.assessment.id: item for item in results}


def command_check(args) -> int:
    assessments, proposals = paths(args)
    try:
        rubric = load_rubric()
        company = load_company()
        results = load_results(assessments)
        offers = load_offers(proposals, company)
        slides.load_style()
    except ContentError as error:
        return report_problems(error)
    print(
        f"Рубрика версии {rubric.version} и профиль компании версии {company.version} в порядке. "
        f"Оценок: {len(results)}, предложений: {len(offers)}."
    )
    notes = [(result.assessment.id, note) for result in results for note in result.notes]
    for offer in offers:
        book = proposal.ProposalBook(offer, company, None, assessment=None)
        # Устаревшие факты профиля печатаются один раз, ниже: повторять их для каждого
        # предложения бессмысленно, источник у них общий.
        notes += [
            (offer.id, note)
            for note in book.warnings()
            if not note.startswith("факт ") and "не найдена" not in note
        ]
    if stale := company.stale_facts():
        notes += [
            ("company.yaml", f"«{fact['label']}: {fact['value']}» верно на {fact['as_of']}")
            for fact in stale
        ]
    if notes:
        print(f"\nЗамечания ({len(notes)}) — не ломают сборку, но требуют внимания:")
        for where, note in notes:
            print(f"- {where}: {note}")
    drafts = [item.assessment.id for item in results if item.assessment.status != "final"]
    drafts += [item.id for item in offers if item.status != "final"]
    if drafts:
        print(f"\nНе итоговые (полные проверки включатся на final): {', '.join(drafts)}")
    return 0


def command_score(args) -> int:
    assessments, _ = paths(args)
    try:
        results = load_results(assessments)
    except ContentError as error:
        return report_problems(error)
    if not results:
        print(f"В {assessments} нет оценок.")
        return 0
    width = max(len(row["name"]) for row in portfolio(results))
    print(f"{'Проект'.ljust(width)}  Балл  Охват  Решение")
    for row in portfolio(results):
        blockers = f"  блокеры: {', '.join(row['blockers'])}" if row["blockers"] else ""
        print(
            f"{row['name'].ljust(width)}  {row['overall']:4.0f}  "
            f"{row['coverage']:4.0f}%  {row['verdict']['name']}{blockers}"
        )
    if args.verbose:
        for result in results:
            print(f"\n{result.assessment.name}")
            for item in result.dimensions:
                mark = item.level if item.scored else "—"
                print(
                    f"  {item.name:<34} вес {item.weight:g}  уровень {mark}"
                    + ("  (блокирующее)" if item.blocking else "")
                )
    return 0


def command_company(args) -> int:
    try:
        company = load_company()
    except ContentError as error:
        return report_problems(error)
    organisation = company.organisation
    print(
        f"{organisation['name']} ({organisation['legal_name']}), профиль версии {company.version}"
    )
    for fact in company.facts:
        mark = " ← подтвердить" if fact in company.stale_facts() else ""
        print(f"  {fact['label']}: {fact['value']}  [{fact['source']}, {fact['as_of']}]{mark}")
    print(
        f"\nУслуг: {len(company.offerings)}, кейсов: {len(company.proof)}, "
        f"отраслей: {len(company.industries)}"
    )
    return 0


def command_build(args) -> int:
    assessments, proposals = paths(args)
    try:
        rubric = load_rubric()
        company = load_company()
        results = load_results(assessments)
        offers = load_offers(proposals, company)
    except ContentError as error:
        return report_problems(error)
    figures = charts.write_figures(args.docs / "assets", results, rubric) if results else []
    pages = render.write_docs(args.docs, results, rubric) if results else []
    if offers:
        figures += charts.write_proposal_figures(args.docs / "assets", offers)
        pages += render.write_proposal_docs(args.docs, offers, company, linked_assessments(results))
    print(f"Фигур: {len(figures)}. Страниц: {len(pages)}.")
    for path in pages:
        print(f"- {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    return 0


def command_pdf(args) -> int:
    assessments, _ = paths(args)
    argv = [
        "--input",
        str(assessments),
        "--out",
        str(args.out),
        "--assets",
        str(args.docs / "assets"),
    ]
    if args.only:
        argv += ["--only", args.only]
    if args.brief:
        argv.append("--brief")
    if args.font:
        argv += ["--font", args.font]
    return pdf.main(argv)


def command_proposal(args) -> int:
    assessments, proposals = paths(args)
    try:
        company = load_company()
        offers = load_offers(proposals, company)
        results = load_results(assessments)
    except ContentError as error:
        return report_problems(error)
    if args.only:
        offers = [item for item in offers if item.id == args.only]
    if not offers:
        print(f"Предложений не найдено в {proposals}", file=sys.stderr)
        return 1
    out = args.out.resolve()
    manifests = proposal.build(
        offers,
        company,
        out,
        (args.docs / "assets").resolve(),
        assessments=linked_assessments(results),
        font=args.font,
    )
    for manifest in manifests:
        print(pdf.report_line(out, manifest))
    return 0


def command_new(args) -> int:
    template = TEMPLATES / f"{args.kind}.yaml"
    assessments, proposals = paths(args)
    target_dir = proposals if args.kind == "proposal" else assessments
    target = target_dir / f"{args.id}.yaml"
    if target.exists():
        print(f"{target} уже существует", file=sys.stderr)
        return 1
    if not template.is_file():
        print(f"Не найден шаблон {template}", file=sys.stderr)
        return 1
    today = dt.date.today().isoformat()
    body = (
        template.read_text(encoding="utf-8")
        .replace("ЗАМЕНИТЕ-ИДЕНТИФИКАТОР", args.id)
        .replace("ЗАМЕНИТЕ-ДАТУ", today)
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    print(f"Создан {target}. Заполняйте по ходу работы, проверяйте `assess check`.")
    return 0


def command_deck(args) -> int:
    """Собирает презентацию, написанную руками: концепцию, ТЗ, материал встречи."""
    try:
        company = load_company()
        built = [deck.load(path, company) for path in args.spec]
        for item in built:
            manifest = slides.build(item, args.out)
            print(f"{args.out / manifest['output']}: слайдов — {manifest['slides']}")
            print(f"Превью для визуальной проверки: {manifest['workspace']}/preview")
    except ContentError as error:
        return report_problems(error)
    return 0


def command_slides(args) -> int:
    assessments, proposals = paths(args)
    try:
        company = load_company()
        results = load_results(assessments)
        if args.kind == "proposal":
            offers = load_offers(proposals, company)
            if args.only:
                offers = [offer for offer in offers if offer.id == args.only]
            linked = linked_assessments(results)
            decks = [
                slides.proposal_deck(offer, company, linked.get(offer.assessment_id))
                for offer in offers
            ]
        else:
            if args.only:
                results = [result for result in results if result.assessment.id == args.only]
            decks = [slides.assessment_deck(result, company) for result in results]
        if not decks:
            print("Не найдены исходные данные для презентации", file=sys.stderr)
            return 1
        for item in decks:
            manifest = slides.build(item, args.out)
            print(f"{args.out / manifest['output']}: слайдов — {manifest['slides']}")
            print(f"Превью для визуальной проверки: {manifest['workspace']}/preview")
    except ContentError as error:
        return report_problems(error)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="assess",
        description="Оценка проектов ИИ-агентов и коммерческие предложения",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "assessments",
        help="каталог с оценками или один файл (по умолчанию assessments/)",
    )
    parser.add_argument(
        "--proposals",
        type=Path,
        default=ROOT / "proposals",
        help="каталог с коммерческими предложениями (по умолчанию proposals/)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="работать с вымышленными примерами из examples/",
    )
    parser.add_argument("--docs", type=Path, default=ROOT / "docs")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("check", help="проверить рубрику, профиль компании, оценки и предложения")
    scored = commands.add_parser("score", help="показать баллы в терминале")
    scored.add_argument("--verbose", action="store_true", help="расписать измерения")
    commands.add_parser("company", help="показать профиль компании и свежесть фактов")
    commands.add_parser("build", help="собрать фигуры и страницы в docs/")
    printed = commands.add_parser("pdf", help="напечатать отчёты по оценкам")
    printed.add_argument("--out", type=Path, default=ROOT / "dist" / "pdf")
    printed.add_argument("--only", help="идентификатор одной оценки")
    printed.add_argument("--brief", action="store_true")
    printed.add_argument("--font")
    offered = commands.add_parser("proposal", help="напечатать коммерческие предложения")
    offered.add_argument("--out", type=Path, default=ROOT / "dist" / "kp")
    offered.add_argument("--only", help="идентификатор одного предложения")
    offered.add_argument("--font")
    presented = commands.add_parser("slides", help="собрать редактируемую презентацию PPTX")
    presented.add_argument("--out", type=Path, default=ROOT / "dist" / "slides")
    presented.add_argument("--only", help="идентификатор одной оценки или предложения")
    presented.add_argument("--kind", choices=["assessment", "proposal"], default="assessment")
    authored = commands.add_parser("deck", help="собрать презентацию по описанию")
    authored.add_argument("--spec", type=Path, nargs="+", required=True, help="YAML с описанием")
    authored.add_argument("--out", type=Path, default=ROOT / "dist" / "slides")
    created = commands.add_parser("new", help="создать файл из шаблона")
    created.add_argument("id", help="идентификатор в kebab-case, он же имя файла")
    created.add_argument(
        "--kind",
        choices=["assessment", "proposal"],
        default="assessment",
        help="что создаём: оценку проекта или коммерческое предложение",
    )

    args = parser.parse_args(argv)
    handlers = {
        "check": command_check,
        "score": command_score,
        "company": command_company,
        "build": command_build,
        "pdf": command_pdf,
        "proposal": command_proposal,
        "deck": command_deck,
        "slides": command_slides,
        "new": command_new,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
