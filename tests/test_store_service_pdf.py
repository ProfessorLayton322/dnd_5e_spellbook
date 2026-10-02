from __future__ import annotations

from pypdf import PdfReader

from spellbook_builder.service import commit_open_batch, prefix_search, validate_indexes, verify_append_only
from spellbook_builder.store import RuntimeStore
from spellbook_builder.util import sha256_file


def test_bundled_catalogue_searches_russian_and_english(tmp_path, bundled_spells):
    store = RuntimeStore(tmp_path / "runtime", bundled_spells)
    assert prefix_search(store.load_spells(), "Огн")[0]["id"] == "dndsu-1"
    assert prefix_search(store.load_spells(), "ice")[0]["id"] == "dndsu-2"
    assert validate_indexes(store) == {"ok": True, "spell_count": 2, "errors": []}


def test_two_batches_preserve_first_segment_and_export_exact_append(tmp_path, bundled_spells):
    store = RuntimeStore(tmp_path / "runtime", bundled_spells)
    book = store.create_spellbook("Книга мага")

    store.begin_batch(book["id"])
    store.add_open_entity(book["id"], {"kind": "spell", "id": "dndsu-1"})
    first = commit_open_batch(store, book["id"])
    first_batch = first["batches"][0]
    first_segment = store.spellbook_dir(book["id"]) / first_batch["segment"]
    first_bytes = first_segment.read_bytes()
    assert first_batch["page_start"] == 1

    store.begin_batch(book["id"])
    store.add_open_entity(book["id"], {"kind": "spell", "id": "dndsu-2"})
    second = commit_open_batch(store, book["id"])
    second_batch = second["batches"][1]
    second_segment = store.spellbook_dir(book["id"]) / second_batch["segment"]
    append = store.spellbook_dir(book["id"]) / "exports" / second_batch["id"] / "append.pdf"

    assert first_segment.read_bytes() == first_bytes
    assert second_batch["page_start"] == first_batch["page_end"] + 1
    assert append.read_bytes() == second_segment.read_bytes()
    assert sha256_file(append) == second_batch["segment_sha256"]
    assert verify_append_only(store, book["id"])["ok"] is True

    full = store.spellbook_dir(book["id"]) / "full.pdf"
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(full)).pages)
    assert "Книга мага" in text
    assert "Огненная искра" in text
    assert "Ледяная игла" in text


def test_short_spells_share_a_page_within_one_batch(tmp_path, bundled_spells):
    store = RuntimeStore(tmp_path / "runtime", bundled_spells)
    book = store.create_spellbook("Flow")
    store.begin_batch(book["id"])
    store.add_open_entity(book["id"], {"kind": "spell", "id": "dndsu-1"})
    store.add_open_entity(book["id"], {"kind": "spell", "id": "dndsu-2"})
    committed = commit_open_batch(store, book["id"])
    pages = [entity["page"] for entity in committed["batches"][0]["entities"]]
    assert pages == [1, 1]
