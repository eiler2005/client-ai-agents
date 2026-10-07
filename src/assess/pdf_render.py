"""Отрисовка PDF консалтингового вида: безопасное подмножество Markdown → A4.

Вёрстка живёт в репозитории, а не во внешней зависимости: документ уходит заказчику,
и его оформление должно меняться здесь, без оглядки на чужие релизы.

Что поддерживается: заголовки, абзацы, выделение, списки, таблицы, http(s)-ссылки,
маркер разрыва страницы `<!-- pagebreak -->` и локальные PNG/JPEG. HTML в разметке
не исполняется. Картинка берётся только из каталога ресурсов сборки — ни URL,
ни произвольный путь в рендерер не попадают.

Ни сети, ни обращений к моделям здесь нет: отчёт по клиенту печатается локально.

Лицензионные условия для этого файла — в LICENSE в корне репозитория.
"""

from __future__ import annotations

import hashlib
import html
import io
import math
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

# Палитра отчёта. Один тёмно-синий «чернильный» тон для текста и заголовков первого
# уровня, один акцент для вторых уровней, линеек и ссылок, серый для подписей.
# Под фирменный стиль меняются эти четыре значения и ничего больше.
INK = colors.HexColor("#18364b")
ACCENT_HEX = "#137c80"
ACCENT = colors.HexColor(ACCENT_HEX)
MUTED = colors.HexColor("#617180")
PALE = colors.HexColor("#eff5f7")
RULE = colors.HexColor("#d9e3e8")
ZEBRA = colors.HexColor("#fafcfc")

FONT_CANDIDATES = (
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "Arial Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", None),
)

PAGEBREAK = "<!-- pagebreak -->"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fonts(font_path: str | None = None) -> tuple[str, str]:
    """Регистрирует обычное и полужирное начертание, возвращает их имена."""
    candidates = [(font_path, None)] if font_path else FONT_CANDIDATES
    for value, bold_name in candidates:
        if value and Path(value).is_file():
            path = Path(value)
            bold = path.with_name(bold_name) if bold_name else path
            if not bold.is_file():
                bold = path
            # Имя от содержимого файла: два разных шрифта не столкнутся в реестре.
            name = "Report-" + digest(path.read_bytes())[:12]
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(path)))
                pdfmetrics.registerFont(TTFont(name + "-Bold", str(bold)))
                pdfmetrics.registerFontFamily(
                    name, normal=name, bold=name + "-Bold", italic=name, boldItalic=name + "-Bold"
                )
            return name, name + "-Bold"
    raise ValueError("Нужен Unicode TTF шрифт; передайте --font PATH")


def font_files(font: str | None = None) -> tuple[Path, Path]:
    """Те же два файла, что выберет `fonts`, — для манифеста и проверки глифов."""
    for value, bold_name in [(font, None)] if font else FONT_CANDIDATES:
        if value and Path(value).is_file():
            path = Path(value)
            bold = path.with_name(bold_name) if bold_name else path
            return path, bold if bold.is_file() else path
    raise ValueError("Нужен Unicode TTF шрифт; передайте --font PATH")


def missing_glyphs(markdown: str, font_path: Path) -> list[str]:
    """Символы, которых нет в шрифте: пустой квадрат в отчёте клиенту недопустим."""
    cmap = TTFont("ReportProbe", str(font_path)).face.charToGlyph
    return sorted({char for char in markdown if not char.isspace() and ord(char) not in cmap})


class Styles:
    def __init__(self, font_path: str | None = None, font_size: float = 11):
        self.font, bold = fonts(font_path)
        if not isinstance(font_size, (int, float)) or not math.isfinite(font_size):
            raise ValueError("Размер шрифта должен быть числом")
        if not 8 <= font_size <= 18:
            raise ValueError("Размер шрифта PDF — от 8 до 18 пунктов")
        self.font_size = float(font_size)
        self.bold = bold
        self.body = ParagraphStyle(
            "DocumentBody",
            fontName=self.font,
            fontSize=self.font_size,
            leading=round(self.font_size * 1.45, 2),
            textColor=INK,
            spaceAfter=6,
            allowWidows=0,
            allowOrphans=0,
            splitLongWords=True,
        )
        small_size = max(8, self.font_size - 1)
        self.small = ParagraphStyle(
            "DocumentSmall",
            parent=self.body,
            fontSize=small_size,
            leading=round(small_size * 1.35, 2),
        )
        self.code = ParagraphStyle(
            "DocumentCode",
            parent=self.small,
            backColor=PALE,
            borderPadding=7,
            spaceBefore=5,
            spaceAfter=8,
        )
        self.caption = ParagraphStyle(
            "DocumentCaption",
            parent=self.small,
            textColor=MUTED,
            spaceAfter=10,
        )
        self.cover_title = ParagraphStyle(
            "CoverTitle",
            parent=self.body,
            fontName=bold,
            fontSize=28,
            leading=33,
            spaceAfter=10,
        )
        self.cover_subtitle = ParagraphStyle(
            "CoverSubtitle",
            parent=self.body,
            fontSize=15,
            leading=21,
            textColor=ACCENT,
            spaceAfter=18,
        )
        self.cover_meta = ParagraphStyle(
            "CoverMeta",
            parent=self.small,
            textColor=MUTED,
            leading=16,
            spaceAfter=3,
        )
        self.headings = {
            n: ParagraphStyle(
                f"DocumentHeading{n}",
                parent=self.body,
                fontName=bold,
                fontSize={1: 22, 2: 15, 3: self.font_size + 1}.get(n, self.font_size),
                leading={1: 27, 2: 20, 3: round((self.font_size + 1) * 1.4, 2)}.get(
                    n, round(self.font_size * 1.4, 2)
                ),
                textColor=INK if n == 1 else ACCENT,
                spaceBefore=15 if n > 1 else 4,
                spaceAfter=8,
                keepWithNext=True,
            )
            for n in range(1, 7)
        }


def _inline(tokens: list) -> str:
    output: list[str] = []
    links: list[bool] = []
    for token in tokens:
        kind = token.type
        if kind in {"text", "html_inline"}:
            output.append(html.escape(token.content))
        elif kind in {"softbreak", "hardbreak"}:
            output.append("<br/>" if kind == "hardbreak" else " ")
        elif kind == "code_inline":
            output.append(f'<font color="{ACCENT_HEX}">{html.escape(token.content)}</font>')
        elif kind in {"strong_open", "strong_close", "em_open", "em_close"}:
            output.append(
                {
                    "strong_open": "<b>",
                    "strong_close": "</b>",
                    "em_open": "<i>",
                    "em_close": "</i>",
                }[kind]
            )
        elif kind == "link_open":
            href = token.attrGet("href") or ""
            safe = urlsplit(href).scheme.lower() in {"https", "http", "mailto"}
            links.append(safe)
            if safe:
                output.append(f'<link href="{html.escape(href, quote=True)}" color="{ACCENT_HEX}">')
        elif kind == "link_close":
            if links.pop():
                output.append("</link>")
        elif kind == "image":
            output.append(html.escape(token.content))
    return "".join(output)


def _image(
    token,
    source_dir: Path | None,
    resource_root: Path | None,
    width: float,
    height: float,
    resources: dict[str, str] | None,
):
    """Картинка только из каталога сборки: ни URL, ни путь наружу рендерер не увидит."""
    src = token.attrGet("src") or ""
    parsed = urlsplit(src)
    if parsed.scheme or parsed.netloc or not source_dir or not resource_root:
        raise ValueError("Картинка в PDF берётся только из локального каталога сборки")
    path = (source_dir / unquote(parsed.path)).resolve()
    if not path.is_relative_to(resource_root.resolve()):
        raise ValueError("Картинка выходит за каталог сборки")
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg"} or not path.is_file():
        raise ValueError("Поддерживаются существующие локальные PNG и JPEG")
    data = path.read_bytes()
    if len(data) > 20_000_000:
        raise ValueError("Картинка больше лимита 20 МБ")
    if resources is not None:
        resources[path.relative_to(resource_root.resolve()).as_posix()] = digest(data)
    picture = Image(io.BytesIO(data))
    ratio = min(width / picture.imageWidth, height / picture.imageHeight, 1)
    picture.drawWidth = picture.imageWidth * ratio
    picture.drawHeight = picture.imageHeight * ratio
    picture.hAlign = "LEFT"
    return picture


class _ReportTable(LongTable):
    def split(self, availWidth, availHeight):
        # Обычная строка, которая не влезла, уезжает на следующую страницу целиком.
        # Делить внутри строки можно только тому, что не помещается и на чистой
        # странице, иначе ReportLab повторит шапку посреди текущей.
        frame = getattr(self, "_frame", None)
        previous = self.splitInRow
        if frame is not None and not frame._atTop:
            self.splitInRow = 0
        try:
            parts = super().split(availWidth, availHeight)
            for part in parts:
                if isinstance(part, _ReportTable):
                    part.splitInRow = previous
            return parts
        finally:
            self.splitInRow = previous


def _column_widths(
    texts: list[list[str]], count: int, width: float, font: str, size: float
) -> list[float]:
    """Ширина колонки по её содержимому, но не уже самого длинного слова в ней.

    Равные колонки читаются плохо: «Вес» получает столько же места, сколько
    «Наблюдение». Доля колонки считается по самой длинной ячейке, сжатой логарифмом,
    иначе одна длинная строка съедает таблицу. Поверх доли действует минимум — ширина
    самого длинного неразрывного слова: без него ReportLab рвёт «Безопасность» на
    «Безопасно» и «сть», и таблица выглядит сломанной.
    """
    padding = 14
    share: list[float] = []
    minimum: list[float] = []
    for column in range(count):
        cells = [row[column] for row in texts if column < len(row)]
        longest = max((len(cell) for cell in cells), default=1)
        share.append(1 + math.log1p(max(longest, 1)) ** 1.6)
        word = max(
            (pdfmetrics.stringWidth(part, font, size) for cell in cells for part in cell.split()),
            default=0.0,
        )
        minimum.append(min(word + padding, width / 2))
    total = sum(share) or 1
    widths = [
        max(width * value / total, floor) for value, floor in zip(share, minimum, strict=True)
    ]
    excess = sum(widths) - width
    if excess > 0.5:
        flexible = [index for index, value in enumerate(widths) if value > minimum[index]]
        pool = sum(widths[index] - minimum[index] for index in flexible)
        if pool > 0:
            take = min(excess, pool)
            for index in flexible:
                widths[index] -= (widths[index] - minimum[index]) / pool * take
    return widths


def _table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), PALE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
            ("LINEBELOW", (0, 0), (-1, 0), 1, ACCENT),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
    )


def markdown_flowables(
    markdown: str,
    width: float,
    *,
    styles: Styles | None = None,
    source_dir: Path | None = None,
    resource_root: Path | None = None,
    resources: dict[str, str] | None = None,
    image_height: float = 175 * mm,
) -> list:
    """Безопасное подмножество Markdown во flowables ReportLab."""
    styles = styles or Styles()
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    # Разбираем любую ссылку, чтобы политика ресурсов отказала явно, а не превратила
    # недопустимую картинку в литеральный текст.
    parser.validateLink = lambda _url: True
    tokens = parser.parse(markdown)
    story: list = []
    lists: list[list] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        kind = token.type
        if kind == "table_open":
            rows: list[list] = []
            texts: list[list[str]] = []
            row: list = []
            raw: list[str] = []
            index += 1
            while tokens[index].type != "table_close":
                part = tokens[index]
                if part.type == "tr_open":
                    row, raw = [], []
                elif part.type == "inline":
                    if any(child.type == "image" for child in part.children or []):
                        raise ValueError("Картинки в PDF ставятся вне ячеек таблицы")
                    row.append(Paragraph(_inline(part.children or []), styles.small))
                    raw.append(part.content)
                elif part.type == "tr_close":
                    rows.append(row)
                    texts.append(raw)
                index += 1
            if rows:
                count = len(rows[0])
                table = _ReportTable(
                    rows,
                    colWidths=_column_widths(
                        texts, count, width, styles.font, styles.small.fontSize
                    ),
                    repeatRows=1,
                    splitByRow=1,
                    splitInRow=1,
                    hAlign="LEFT",
                )
                table.setStyle(_table_style())
                story.extend([table, Spacer(1, 10)])
        elif kind in {"bullet_list_open", "ordered_list_open"}:
            lists.append([kind == "ordered_list_open", int(token.attrGet("start") or 1)])
        elif kind in {"bullet_list_close", "ordered_list_close"}:
            lists.pop()
        elif kind == "inline":
            previous = tokens[index - 1]
            children = token.children or []
            if token.content.strip() == PAGEBREAK:
                story.append(PageBreak())
            else:
                style = (
                    styles.headings[int(previous.tag[1:])]
                    if previous.type == "heading_open"
                    else styles.body
                )
                text = _inline(children)
                prefix = ""
                if lists and previous.type == "paragraph_open":
                    ordered, number = lists[-1]
                    marker = f"{number}." if ordered else "•"
                    # Маркер получает только первый абзац пункта.
                    first = index >= 2 and tokens[index - 2].type == "list_item_open"
                    if first:
                        lists[-1][1] += 1
                    style = ParagraphStyle(
                        "DocumentList",
                        parent=styles.body,
                        leftIndent=13 * len(lists),
                        firstLineIndent=-10 if first else 0,
                    )
                    if first:
                        prefix = html.escape(marker) + "  "
                        text = prefix + text
                image_tokens = [child for child in children if child.type == "image"]
                if image_tokens:
                    others = [child for child in children if child.type != "image"]
                    if _inline(others).strip() or prefix:
                        story.append(Paragraph(prefix + _inline(others), style))
                    for child in image_tokens:
                        story.append(
                            _image(child, source_dir, resource_root, width, image_height, resources)
                        )
                        if child.content:
                            story.append(Paragraph(html.escape(child.content), styles.caption))
                else:
                    story.append(Paragraph(text or " ", style))
                    if previous.type == "heading_open":
                        story[-1]._document_heading = (int(previous.tag[1:]), token.content)
        elif kind in {"fence", "code_block"}:
            # Отдельные абзацы позволяют длинному блоку кода разъехаться по страницам.
            for line in token.content.splitlines():
                value = html.escape(line.expandtabs(4)).replace(" ", "&#160;")
                story.append(Paragraph(value or "&#160;", styles.code))
        elif kind == "hr":
            story.append(HRFlowable(width="100%", thickness=0.5, color=ACCENT, spaceAfter=9))
        index += 1
    _keep_leads_with_content(story)
    return story


def _keep_leads_with_content(story: list) -> None:
    """Вводный абзац остаётся на странице вместе с тем, что он вводит.

    ReportLab сам держит так только заголовки. В отчёте же половина смысла лежит в
    строках вида «**Наблюдение:** …», «**Риск:** …» перед списком или таблицей:
    оторванная от своего блока, такая строка читается как потерянная. Абзац, который
    начинается с полужирного или курсива, прижимается к следующему блоку — но никогда
    через заголовок, иначе цепочка перетечёт в следующий раздел и перерастёт страницу.
    """

    def style_name(flowable) -> str:
        return getattr(getattr(flowable, "style", None), "name", "")

    for flowable, following in zip(story, story[1:], strict=False):
        opens = getattr(flowable, "text", "").startswith(("<b>", "<i>"))
        before_heading = style_name(following).startswith("DocumentHeading")
        if style_name(flowable) == "DocumentBody" and opens and not before_heading:
            flowable.keepWithNext = 1


class _Document(SimpleDocTemplate):
    """Шаблон, который попутно собирает закладки PDF из заголовков."""

    def afterFlowable(self, flowable):
        heading = getattr(flowable, "_document_heading", None)
        if heading:
            level, title = heading
            count = getattr(self, "_heading_count", 0)
            key = f"heading-{count}"
            self._heading_count = count + 1
            self.canv.bookmarkPage(key)
            # В оглавлении PDF нельзя перескакивать через уровень.
            actual = min(level - 1, getattr(self, "_outline_level", -1) + 1)
            self._outline_level = actual
            self.canv.addOutlineEntry(title, key, level=actual, closed=False)


def _cover_flowables(cover: dict, styles: Styles) -> list:
    """Титул: заголовок, подзаголовок, строки реквизитов и пометка конфиденциальности."""
    story = [Spacer(1, 45 * mm), Paragraph(html.escape(cover["title"]), styles.cover_title)]
    if cover.get("subtitle"):
        story.append(Paragraph(html.escape(cover["subtitle"]), styles.cover_subtitle))
    story.append(HRFlowable(width="55%", thickness=1.2, color=ACCENT, spaceAfter=14))
    for line in cover.get("meta", []):
        story.append(Paragraph(line, styles.cover_meta))
    if cover.get("notice"):
        story.append(Spacer(1, 18 * mm))
        story.append(Paragraph(html.escape(cover["notice"]), styles.cover_meta))
    story.append(PageBreak())
    return story


def render_markdown(
    markdown: str,
    *,
    title: str | None = None,
    subtitle: str | None = None,
    cover: dict | None = None,
    footer: str | None = None,
    font_path: str | None = None,
    font_size: float = 11,
    wide: bool = False,
    source_dir: Path | None = None,
    resource_root: Path | None = None,
    resources: dict[str, str] | None = None,
) -> bytes:
    """Markdown → байты PDF. `cover` печатает титул без колонтитулов."""
    styles = Styles(font_path, font_size)
    first = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    inferred = first.group(1) if first else "Документ"
    display_title = title or (cover or {}).get("title") or inferred
    target = io.BytesIO()
    document = _Document(
        target,
        pagesize=landscape(A4) if wide else A4,
        leftMargin=19 * mm,
        rightMargin=19 * mm,
        topMargin=20 * mm,
        bottomMargin=19 * mm,
        title=display_title,
        author="",
        invariant=1,
    )
    story: list = []
    if cover:
        story += _cover_flowables(cover, styles)
    if title and not cover:
        story.append(Paragraph(html.escape(title), styles.headings[1]))
    if subtitle:
        story.append(Paragraph(html.escape(subtitle), styles.caption))
    story += markdown_flowables(
        markdown,
        document.width,
        styles=styles,
        source_dir=source_dir,
        resource_root=resource_root,
        resources=resources,
        image_height=document.height - 60,
    )
    if not story:
        story.append(Paragraph(" ", styles.body))

    def furniture(canv, doc):
        if cover and doc.page == 1:
            return
        canv.saveState()
        page_width, page_height = doc.pagesize
        canv.setStrokeColor(ACCENT)
        canv.setLineWidth(1.2)
        canv.line(
            doc.leftMargin,
            page_height - 12 * mm,
            page_width - doc.rightMargin,
            page_height - 12 * mm,
        )
        canv.setFont(styles.font, 7)
        canv.setFillColor(MUTED)
        label = footer or display_title
        while pdfmetrics.stringWidth(label, styles.font, 7) > doc.width - 50 and label:
            label = label[:-1]
        canv.drawString(doc.leftMargin, 10 * mm, label)
        canv.drawRightString(page_width - doc.rightMargin, 10 * mm, str(doc.page))
        canv.restoreState()

    document.build(story, onFirstPage=furniture, onLaterPages=furniture)
    return target.getvalue()


def inspect_pdf(data: bytes) -> dict:
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("Зашифрованные PDF не поддерживаются")
    return {"pages": len(reader.pages), "sha256": digest(data), "bytes": len(data)}


def part_pages(data: bytes) -> list[int]:
    """Страницы (с единицы) верхних записей оглавления: по одной на каждый H1."""
    reader = PdfReader(io.BytesIO(data))
    return [
        reader.get_destination_page_number(item) + 1
        for item in reader.outline
        if not isinstance(item, list)
    ]


def extract_text(data: bytes) -> str:
    """Текст всех страниц — для проверки готового файла перед отправкой клиенту."""
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)
