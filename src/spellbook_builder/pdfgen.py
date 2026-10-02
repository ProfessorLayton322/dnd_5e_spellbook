from __future__ import annotations

import os
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer


# 1: continuous best-effort flow; only the beginning of a committed batch
# starts a fresh segment/page. Historical segments are never re-rendered.
RENDERER_VERSION = 1
PACKAGE_ROOT = Path(__file__).resolve().parent
REGULAR_FONT = PACKAGE_ROOT / "static" / "DejaVuSans.ttf"
BOLD_FONT = PACKAGE_ROOT / "static" / "DejaVuSans-Bold.ttf"


def _register_fonts() -> None:
    if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVuSans", str(REGULAR_FONT)))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(BOLD_FONT)))
        pdfmetrics.registerFontFamily(
            "DejaVuSans",
            normal="DejaVuSans",
            bold="DejaVuSans-Bold",
            italic="DejaVuSans",
            boldItalic="DejaVuSans-Bold",
        )


def _safe(value) -> str:
    return escape(str(value if value is not None else ""))


class EntityMarker(Flowable):
    def __init__(self, entity_index: int, title: str, anchors: list[dict], logical_offset: int):
        super().__init__()
        self.entity_index = entity_index
        self.title = title
        self.anchors = anchors
        self.logical_offset = logical_offset
        self.width = 0
        self.height = 0

    def wrap(self, _available_width, _available_height):
        return (0, 0)

    def draw(self):
        self.anchors.append(
            {
                "entity_index": self.entity_index,
                "title": self.title,
                "page": self.canv.getPageNumber() + self.logical_offset,
            }
        )


def _styles():
    _register_fonts()
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="EntityTitle",
            parent=styles["Title"],
            fontName="DejaVuSans-Bold",
            fontSize=15,
            leading=18,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Section",
            parent=styles["Heading3"],
            fontName="DejaVuSans-Bold",
            fontSize=9.5,
            leading=12,
            spaceBefore=6,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodySmall",
            parent=styles["BodyText"],
            fontName="DejaVuSans",
            fontSize=8.3,
            leading=10.7,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Meta",
            parent=styles["BodyText"],
            fontName="DejaVuSans",
            fontSize=7.2,
            leading=9,
            textColor=colors.HexColor("#555555"),
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TOCTitle",
            parent=styles["Title"],
            fontName="DejaVuSans-Bold",
            alignment=TA_CENTER,
            fontSize=18,
            leading=22,
            spaceAfter=16,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TOCEntry",
            parent=styles["BodyText"],
            fontName="DejaVuSans",
            fontSize=8.3,
            leading=10.5,
            leftIndent=5,
            rightIndent=5,
            spaceAfter=2,
        )
    )
    return styles


def _line(label: str, value, styles) -> Paragraph | None:
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    return Paragraph(f"<b>{_safe(label)}:</b> {_safe(value)}", styles["BodySmall"])


def _block_flowables(blocks: list[dict], styles) -> list:
    story: list = []
    for block in blocks:
        text = block.get("text", "")
        if not text:
            continue
        if block.get("type") == "heading":
            story.append(Paragraph(_safe(text), styles["Section"]))
        else:
            story.append(Paragraph(_safe(text).replace("\n", "<br/>"), styles["BodySmall"]))
    return story


def entity_separator() -> Flowable:
    return HRFlowable(width="100%", thickness=1, lineCap="butt", color=colors.black, spaceBefore=9, spaceAfter=9)


def spell_flowables(spell: dict, styles) -> tuple[list, list]:
    level = "Заговор" if spell.get("level") == 0 else f"{spell.get('level')} уровень"
    subtitle = f"{level}, {spell.get('school', '')}"
    if spell.get("ritual"):
        subtitle += " (ритуал)"
    heading = [
        Paragraph(_safe(spell["name"]), styles["EntityTitle"]),
        Paragraph(_safe(subtitle), styles["BodySmall"]),
    ]
    body: list = []
    fields = spell.get("parameters", {})
    preferred = ["Время накладывания", "Дистанция", "Компоненты", "Длительность", "Классы", "Подклассы"]
    for label in preferred:
        flowable = _line(label, fields.get(label), styles)
        if flowable:
            body.append(flowable)
    for label, value in fields.items():
        if label not in preferred:
            flowable = _line(label, value, styles)
            if flowable:
                body.append(flowable)
    body.append(Spacer(1, 4))
    body.extend(_block_flowables(spell.get("content_blocks", []), styles))
    source = spell.get("source_book") or spell.get("source_code")
    if source:
        body.append(Paragraph(f"Источник: {_safe(source)}", styles["Meta"]))
    return heading, body


def _atomic_pdf_target(path: Path) -> tuple[Path, Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    return Path(name), path


def render_batch_segment(
    path: Path,
    entities: list[dict],
    spells: dict,
    logical_page_start: int,
) -> tuple[int, list[dict]]:
    if not entities:
        raise ValueError("Cannot render an empty batch")
    styles = _styles()
    anchors: list[dict] = []
    story: list = []
    offset = logical_page_start - 1
    for index, entity in enumerate(entities):
        if entity["kind"] != "spell":
            raise ValueError(f"Unknown printable entity kind: {entity['kind']}")
        heading, body = spell_flowables(spells[entity["id"]], styles)
        # Keep the separator, title, subtitle and first details line together.
        # Everything else flows into remaining page space and onto later pages.
        group = [entity_separator()] if index else []
        group += [EntityMarker(index, entity["title"], anchors, offset), *heading, *body[:1]]
        story.append(KeepTogether(group))
        story.extend(body[1:])

    temp, target = _atomic_pdf_target(path)
    doc = SimpleDocTemplate(
        str(temp),
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )

    def number_page(canvas, _doc):
        logical = canvas.getPageNumber() + offset
        canvas.saveState()
        canvas.setFont("DejaVuSans", 7.5)
        canvas.drawRightString(A4[0] - 12 * mm, 8 * mm, str(logical))
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(12 * mm, 8 * mm, f"D&D 5e Spellbook · renderer {RENDERER_VERSION}")
        canvas.restoreState()

    try:
        doc.build(story, onFirstPage=number_page, onLaterPages=number_page)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    page_count = len(PdfReader(str(target)).pages)
    anchors.sort(key=lambda entry: entry["entity_index"])
    return page_count, anchors


def render_toc(path: Path, spellbook_name: str, entries: list[dict]) -> int:
    styles = _styles()
    story: list = [Paragraph(f"{_safe(spellbook_name)} — Оглавление", styles["TOCTitle"])]
    if not entries:
        story.append(Paragraph("Нет сохранённых страниц.", styles["BodySmall"]))
    for entry in entries:
        title = _safe(entry["title"])
        page = _safe(entry["page"])
        dots = "." * max(3, 76 - min(64, len(entry["title"])))
        story.append(Paragraph(f"{title} {dots} <b>{page}</b>", styles["TOCEntry"]))
    temp, target = _atomic_pdf_target(path)
    try:
        SimpleDocTemplate(
            str(temp),
            pagesize=A4,
            rightMargin=16 * mm,
            leftMargin=16 * mm,
            topMargin=16 * mm,
            bottomMargin=14 * mm,
        ).build(story)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return len(PdfReader(str(target)).pages)


def concatenate_pdfs(path: Path, parts: list[Path]) -> None:
    temp, target = _atomic_pdf_target(path)
    writer = PdfWriter()
    try:
        for part in parts:
            writer.append(str(part))
        with temp.open("wb") as handle:
            writer.write(handle)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def pdf_content_hashes(path: Path) -> list[str]:
    import hashlib

    hashes: list[str] = []
    for page in PdfReader(str(path)).pages:
        content = page.get_contents()
        data = content.get_data() if content else b""
        hashes.append(hashlib.sha256(data).hexdigest())
    return hashes
