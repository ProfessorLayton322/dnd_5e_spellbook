from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from pypdf import PdfReader

from .pdfgen import RENDERER_VERSION, concatenate_pdfs, pdf_content_hashes, render_batch_segment, render_toc
from .store import RuntimeStore
from .util import atomic_json_write, normalized_name, portable_relative_path, resolve_portable_path, sha256_file, utc_now


class ServiceError(RuntimeError):
    pass


def prefix_search(spells: dict[str, dict], prefix: str, limit: int = 25) -> list[dict]:
    wanted = normalized_name(prefix)
    if not wanted:
        return []

    def starts(spell: dict) -> bool:
        candidates = (spell.get("name_ru", ""), spell.get("name_en", ""), spell.get("name", ""))
        return any(normalized_name(candidate).startswith(wanted) for candidate in candidates if candidate)

    matches = [spell for spell in spells.values() if starts(spell)]
    matches.sort(key=lambda spell: (normalized_name(spell.get("name_ru") or spell["name"]), spell["id"]))
    return [
        {
            "id": spell["id"],
            "name": spell["name"],
            "level": spell.get("level", 0),
            "school": spell.get("school", ""),
        }
        for spell in matches[:limit]
    ]


def expand_entities(open_entities: list[dict], spells: dict[str, dict]) -> list[dict]:
    expanded: list[dict] = []
    for source in open_entities:
        if source.get("kind") != "spell" or source.get("id") not in spells:
            raise ServiceError(f"Unknown spell entity: {source}")
        spell = spells[source["id"]]
        expanded.append({"kind": "spell", "id": spell["id"], "title": spell["name"]})
    return expanded


def _copy_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temp = Path(name)
    try:
        shutil.copyfile(source, temp)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def all_toc_entries(book: dict) -> list[dict]:
    return [
        {"title": entity["title"], "page": entity["page"], "kind": entity["kind"], "id": entity["id"]}
        for batch in book["batches"]
        for entity in batch["entities"]
    ]


def commit_open_batch(store: RuntimeStore, spellbook_id: str) -> dict:
    book = store.get_spellbook(spellbook_id)
    open_batch = book.get("open_batch")
    if not open_batch:
        raise ServiceError("There is no open batch")
    if not open_batch["entities"]:
        raise ServiceError("Cannot commit an empty batch")
    if book.get("renderer_version", 1) > RENDERER_VERSION:
        raise ServiceError(
            f"Spellbook uses renderer {book['renderer_version']}, newer than this application's renderer {RENDERER_VERSION}"
        )

    spells = store.load_spells()
    expanded = expand_entities(open_batch["entities"], spells)
    batch_id = open_batch["id"]
    book_dir = store.spellbook_dir(spellbook_id)
    segment = book_dir / "batches" / f"{batch_id}.pdf"
    if segment.exists():
        raise ServiceError(f"Refusing to overwrite immutable batch segment: {segment}")
    page_start = book["content_page_count"] + 1
    page_count, anchors = render_batch_segment(segment, expanded, spells, page_start)
    anchor_map = {entry["entity_index"]: entry for entry in anchors}
    for index, entity in enumerate(expanded):
        entity["page"] = anchor_map[index]["page"]

    committed_at = utc_now()
    batch = {
        "id": batch_id,
        "created_at": open_batch["created_at"],
        "committed_at": committed_at,
        "entities": expanded,
        "page_start": page_start,
        "page_end": page_start + page_count - 1,
        "page_count": page_count,
        "segment": portable_relative_path(segment, book_dir),
        "segment_sha256": sha256_file(segment),
        "renderer_version": RENDERER_VERSION,
    }
    candidate = dict(book)
    candidate["batches"] = book["batches"] + [batch]
    candidate["open_batch"] = None
    candidate["renderer_version"] = RENDERER_VERSION
    candidate["content_page_count"] = batch["page_end"]

    export_dir = book_dir / "exports" / batch_id
    toc_path = export_dir / "toc.pdf"
    append_path = export_dir / "append.pdf"
    render_toc(toc_path, candidate["name"], all_toc_entries(candidate))
    _copy_atomic(segment, append_path)
    full_path = book_dir / "full.pdf"
    segments = [resolve_portable_path(book_dir, historical["segment"]) for historical in candidate["batches"]]
    concatenate_pdfs(full_path, [toc_path, *segments])
    manifest = {
        "schema_version": 1,
        "renderer_version": RENDERER_VERSION,
        "spellbook_id": spellbook_id,
        "batch_id": batch_id,
        "committed_at": committed_at,
        "dataset_generated_at": store.dataset_metadata().get("generated_at"),
        "toc_pdf": portable_relative_path(toc_path, book_dir),
        "append_pdf": portable_relative_path(append_path, book_dir),
        "full_pdf": portable_relative_path(full_path, book_dir),
        "logical_content_page_start": batch["page_start"],
        "logical_content_page_end": batch["page_end"],
        "new_page_count": page_count,
        "cumulative_content_page_count": candidate["content_page_count"],
        "entities": [
            {"kind": item["kind"], "id": item["id"], "title": item["title"], "page": item["page"]}
            for item in expanded
        ],
        "segment_sha256": batch["segment_sha256"],
        "append_sha256": sha256_file(append_path),
        "toc_sha256": sha256_file(toc_path),
        "full_sha256": sha256_file(full_path),
    }
    atomic_json_write(export_dir / "manifest.json", manifest)
    candidate["exports"] = book["exports"] + [manifest]
    store.update_spellbook(candidate)
    return candidate


def render_full_spellbook(store: RuntimeStore, spellbook_id: str) -> Path:
    book = store.get_spellbook(spellbook_id)
    book_dir = store.spellbook_dir(spellbook_id)
    toc = book_dir / "current-toc.pdf"
    render_toc(toc, book["name"], all_toc_entries(book))
    segments = [resolve_portable_path(book_dir, batch["segment"]) for batch in book["batches"]]
    full = book_dir / "full.pdf"
    concatenate_pdfs(full, [toc, *segments])
    return full


def verify_append_only(store: RuntimeStore, spellbook_id: str) -> dict:
    book = store.get_spellbook(spellbook_id)
    if not book["batches"]:
        raise ServiceError("Spellbook has no committed batches")
    book_dir = store.spellbook_dir(spellbook_id)
    full = book_dir / "full.pdf"
    if not full.exists():
        raise ServiceError("Full PDF is missing")
    total_content = sum(batch["page_count"] for batch in book["batches"])
    toc_pages = len(PdfReader(str(full)).pages) - total_content
    full_hashes = pdf_content_hashes(full)
    checked = 0
    failures: list[str] = []
    offset = toc_pages
    for batch in book["batches"]:
        segment = resolve_portable_path(book_dir, batch["segment"])
        segment_hashes = pdf_content_hashes(segment)
        if sha256_file(segment) != batch["segment_sha256"]:
            failures.append(f"{batch['id']}: immutable segment file hash changed")
        if full_hashes[offset : offset + len(segment_hashes)] != segment_hashes:
            failures.append(f"{batch['id']}: full PDF content streams differ from segment")
        append_path = book_dir / "exports" / batch["id"] / "append.pdf"
        if not append_path.is_file() or sha256_file(append_path) != batch["segment_sha256"]:
            failures.append(f"{batch['id']}: append PDF is not an exact segment copy")
        offset += len(segment_hashes)
        checked += len(segment_hashes)
    expected_start = 1
    for batch in book["batches"]:
        if batch["page_start"] != expected_start:
            failures.append(f"{batch['id']}: starts at {batch['page_start']}, expected {expected_start}")
        expected_start = batch["page_end"] + 1
    return {
        "ok": not failures,
        "spellbook_id": spellbook_id,
        "toc_pages": toc_pages,
        "content_pages_checked": checked,
        "batches_checked": len(book["batches"]),
        "failures": failures,
    }


def validate_indexes(store: RuntimeStore) -> dict:
    spells = store.load_spells()
    errors: list[str] = []
    seen_numeric_ids: set[int] = set()
    for key, spell in spells.items():
        if key != spell.get("id"):
            errors.append(f"spell key {key} does not match record ID {spell.get('id')}")
        if not spell.get("name"):
            errors.append(f"spell {key} has no name")
        if not spell.get("content_blocks"):
            errors.append(f"spell {key} has no description")
        numeric_id = spell.get("numeric_id")
        if not isinstance(numeric_id, int) or numeric_id in seen_numeric_ids:
            errors.append(f"spell {key} has invalid or duplicate numeric ID {numeric_id}")
        seen_numeric_ids.add(numeric_id)
        level = spell.get("level")
        if not isinstance(level, int) or not 0 <= level <= 9:
            errors.append(f"spell {key} has invalid level {level}")
    metadata = store.dataset_metadata()
    if metadata["record_count"] != len(spells):
        errors.append(f"metadata says {metadata['record_count']} spells, found {len(spells)}")
    return {"ok": not errors, "spell_count": len(spells), "errors": errors}
