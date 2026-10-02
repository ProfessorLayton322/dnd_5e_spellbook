"""Download and parse the official-spell catalogue published by dnd.su.

The installed application never contacts dnd.su: this module is used by the
maintainer script to produce the bundled ``data/spells.json`` resource.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Tag

from .fetch import Fetcher
from .tables import table_to_text
from .util import atomic_json_write, clean_text, normalized_name, utc_now


BASE_URL = "https://dnd.su"
INDEX_URL = f"{BASE_URL}/spells/"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
SPELL_URL_RE = re.compile(r"^https://dnd\.su/spells/(?P<id>\d+)-[^/]+/$")
TITLE_RE = re.compile(r"^(?P<ru>.*?)\s*\[(?P<en>[^]]+)]\s*$")
LEVEL_RE = re.compile(r"^(?:(?P<level>\d+)\s+уровень|(?P<cantrip>заговор))\s*,\s*(?P<school>.+)$", re.IGNORECASE)
PARSER_VERSION = 1


class DndSuParseError(RuntimeError):
    pass


def discover_spell_urls(sitemap_xml: str) -> list[str]:
    """Return numeric spell-detail URLs from the public sitemap."""

    try:
        root = ElementTree.fromstring(sitemap_xml)
    except ElementTree.ParseError as exc:
        raise DndSuParseError(f"Could not parse {SITEMAP_URL}: {exc}") from exc
    urls: dict[int, str] = {}
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "loc" or not node.text:
            continue
        url = node.text.strip()
        match = SPELL_URL_RE.fullmatch(url)
        if match:
            urls[int(match.group("id"))] = url
    if not urls:
        raise DndSuParseError("The sitemap contained no dnd.su spell detail URLs")
    return [urls[key] for key in sorted(urls)]


def _description_blocks(description: Tag) -> list[dict]:
    blocks: list[dict] = []
    for node in description.find_all(recursive=False):
        if not isinstance(node, Tag):
            continue
        if node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            text = clean_text(node.get_text(" ", strip=True))
            block_type = "heading"
        elif node.name == "table":
            text = table_to_text(node)
            block_type = "table"
        elif node.name in {"ul", "ol"}:
            items = [clean_text(item.get_text(" ", strip=True)) for item in node.find_all("li", recursive=False)]
            marker = (lambda index: f"{index}.") if node.name == "ol" else (lambda _index: "•")
            text = "\n".join(f"{marker(index)} {item}" for index, item in enumerate(items, 1) if item)
            block_type = "list"
        else:
            text = clean_text(node.get_text(" ", strip=True))
            block_type = "paragraph"
        if text:
            blocks.append({"type": block_type, "text": text})
    if not blocks:
        text = clean_text(description.get_text(" ", strip=True))
        if text:
            blocks.append({"type": "paragraph", "text": text})
    return blocks


def parse_spell_page(html: str, source_url: str) -> dict:
    """Parse one spell detail page into the bundled canonical schema."""

    soup = BeautifulSoup(html, "html.parser")
    card = soup.select_one('.card[data-id^="spells:"]')
    if card is None:
        raise DndSuParseError(f"Spell card not found at {source_url}")
    data_id = card.get("data-id", "")
    numeric_id = data_id.partition(":")[2]
    if not numeric_id.isdigit():
        raise DndSuParseError(f"Invalid spell card ID {data_id!r} at {source_url}")

    title_node = card.select_one(".card-title [data-copy]") or card.select_one(".card-title")
    title = clean_text(title_node.get("data-copy") if title_node and title_node.has_attr("data-copy") else title_node.get_text(" ", strip=True) if title_node else "")
    if not title:
        raise DndSuParseError(f"Spell title not found at {source_url}")
    title_match = TITLE_RE.fullmatch(title)
    name_ru = clean_text(title_match.group("ru")) if title_match else title
    name_en = clean_text(title_match.group("en")) if title_match else ""

    params = card.select_one("[itemprop='articleBody'] ul.params")
    if params is None:
        raise DndSuParseError(f"Spell parameters not found at {source_url}")
    top_items = params.find_all("li", recursive=False)
    if not top_items:
        raise DndSuParseError(f"Spell level and school not found at {source_url}")
    level_school = clean_text(top_items[0].get_text(" ", strip=True))
    level_match = LEVEL_RE.fullmatch(level_school)
    if not level_match:
        raise DndSuParseError(f"Could not parse spell level/school {level_school!r} at {source_url}")
    level = 0 if level_match.group("cantrip") else int(level_match.group("level"))
    school = clean_text(level_match.group("school"))
    ritual = "ритуал" in school.casefold()
    school = re.sub(r"\s*\(ритуал\)\s*$", "", school, flags=re.IGNORECASE)

    fields: dict[str, str] = {}
    description: Tag | None = None
    for item in top_items[1:]:
        if "desc" in item.get("class", []):
            description = item.select_one("[itemprop='description']") or item
            continue
        strong = item.find("strong")
        if strong:
            label = clean_text(strong.get_text(" ", strip=True)).rstrip(":")
            strong.extract()
            fields[label] = clean_text(item.get_text(" ", strip=True)).lstrip(": ")
    if description is None:
        raise DndSuParseError(f"Spell description not found at {source_url}")
    blocks = _description_blocks(description)
    if not blocks:
        raise DndSuParseError(f"Spell description was empty at {source_url}")

    source_plaque = card.select_one(".card-title .source-plaque:not(a)") or card.select_one(".card-title .source-plaque")
    source_book = clean_text(source_plaque.get("title", "")) if source_plaque else ""
    source_code = clean_text(source_plaque.get_text(" ", strip=True)) if source_plaque else ""
    duration = fields.get("Длительность", "")
    classes = [
        re.sub(r"\s+TCE\s*$", "", clean_text(value), flags=re.IGNORECASE)
        for value in fields.get("Классы", "").split(",")
        if clean_text(value)
    ]
    subclasses = [clean_text(value) for value in fields.get("Подклассы", "").split(",") if clean_text(value)]
    link_id_match = SPELL_URL_RE.fullmatch(source_url)
    if link_id_match and link_id_match.group("id") != numeric_id:
        raise DndSuParseError(f"Sitemap URL ID and card ID disagree at {source_url}")

    return {
        "schema_version": 1,
        "parser_version": PARSER_VERSION,
        "id": f"dndsu-{numeric_id}",
        "numeric_id": int(numeric_id),
        "name": title,
        "name_ru": name_ru,
        "name_en": name_en,
        "normalized_name": normalized_name(title),
        "level": level,
        "school": school,
        "ritual": ritual,
        "concentration": duration.casefold().startswith("концентрация"),
        "casting_time": fields.get("Время накладывания", ""),
        "range": fields.get("Дистанция", ""),
        "components": fields.get("Компоненты", ""),
        "duration": duration,
        "classes": classes,
        "subclasses": subclasses,
        "parameters": fields,
        "content_blocks": blocks,
        "description": "\n".join(block["text"] for block in blocks),
        "tables": [block["text"] for block in blocks if block["type"] == "table"],
        "source_book": source_book,
        "source_code": source_code,
        "source_url": source_url,
        "fetched_at": utc_now(),
    }


def crawl_spells(
    fetcher: Fetcher,
    output: Path,
    *,
    refresh: bool = False,
    limit: int | None = None,
    on_progress: Callable[[int, int, dict, bool], None] | None = None,
) -> dict:
    """Crawl every sitemap spell and atomically checkpoint one bundled JSON."""

    sitemap = fetcher.get(SITEMAP_URL)
    urls = discover_spell_urls(sitemap)
    if limit is not None:
        urls = urls[: max(0, limit)]
    expected_ids = {f"dndsu-{SPELL_URL_RE.fullmatch(url).group('id')}" for url in urls}

    existing: dict = {}
    if output.is_file() and not refresh:
        import json

        with output.open(encoding="utf-8") as handle:
            existing = json.load(handle).get("records", {})
    records = dict(existing)
    # Small forward migration for checkpoints produced by pre-release parser
    # versions. This preserves resume behavior without keeping stale class
    # labels such as "друид TCE" as separate classes in the app.
    for record in records.values():
        record["classes"] = [
            re.sub(r"\s+TCE\s*$", "", value, flags=re.IGNORECASE)
            for value in record.get("classes", [])
        ]
        record["parser_version"] = PARSER_VERSION
    crawled_at = utc_now()
    for index, url in enumerate(urls, 1):
        numeric_id = SPELL_URL_RE.fullmatch(url).group("id")
        spell_id = f"dndsu-{numeric_id}"
        reused = not refresh and spell_id in records and records[spell_id].get("source_url") == url
        if not reused:
            last_error: DndSuParseError | None = None
            # The host occasionally answers 200 with a partial/chrome-only
            # document. Treat a missing semantic card like a transient HTTP
            # failure and request the page again.
            for _attempt in range(fetcher.retries + 1):
                try:
                    records[spell_id] = parse_spell_page(fetcher.get(url), url)
                    break
                except DndSuParseError as exc:
                    last_error = exc
            else:
                raise last_error or DndSuParseError(f"Could not parse {url}")
            payload = {
                "schema_version": 1,
                "source": INDEX_URL,
                "sitemap": SITEMAP_URL,
                "generated_at": crawled_at,
                "record_count": len(records),
                "records": dict(sorted(records.items(), key=lambda pair: pair[1].get("numeric_id", 0))),
            }
            atomic_json_write(output, payload)
        if on_progress:
            on_progress(index, len(urls), records[spell_id], reused)

    final_records = records if limit is not None else {key: value for key, value in records.items() if key in expected_ids}
    payload = {
        "schema_version": 1,
        "source": INDEX_URL,
        "sitemap": SITEMAP_URL,
        "generated_at": crawled_at,
        "record_count": len(final_records),
        "records": dict(sorted(final_records.items(), key=lambda pair: pair[1]["numeric_id"])),
    }
    atomic_json_write(output, payload)
    return payload
