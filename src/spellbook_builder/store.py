from __future__ import annotations

import json
import os
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

from .pdfgen import RENDERER_VERSION
from .util import atomic_json_write, read_json, slugify, utc_now


PACKAGE_ROOT = Path(__file__).resolve().parent
BUNDLED_SPELLS = PACKAGE_ROOT / "data" / "spells.json"


class StoreError(RuntimeError):
    pass


class RuntimeStore:
    """User spellbook state backed by a read-only, package-owned spell index."""

    def __init__(self, root: Path, bundled_spells: Path | None = None):
        self.root = root
        self.spellbooks_dir = root / "spellbooks"
        self.bundled_spells = bundled_spells or BUNDLED_SPELLS
        self.root.mkdir(parents=True, exist_ok=True)
        self.spellbooks_dir.mkdir(parents=True, exist_ok=True)
        self._remove_stale_atomic_files()
        if not self.state_path.exists():
            self.save_state(self.empty_state())
        self._finish_interrupted_spellbook_deletes()
        self._migrate_state()
        self._spell_document = self._load_bundled_document()

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    @staticmethod
    def empty_state() -> dict:
        return {"schema_version": 1, "spellbooks": {}, "updated_at": utc_now()}

    def load_state(self) -> dict:
        return read_json(self.state_path, self.empty_state())

    def save_state(self, state: dict) -> None:
        state["updated_at"] = utc_now()
        atomic_json_write(self.state_path, state)

    def _load_bundled_document(self) -> dict:
        if not self.bundled_spells.is_file():
            raise StoreError(f"Bundled spell catalogue is missing: {self.bundled_spells}")
        try:
            with self.bundled_spells.open(encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"Could not read bundled spell catalogue: {exc}") from exc
        records = document.get("records")
        if document.get("schema_version") != 1 or not isinstance(records, dict) or not records:
            raise StoreError("Bundled spell catalogue has an unsupported or empty schema")
        return document

    def load_spells(self) -> dict[str, dict]:
        return self._spell_document["records"]

    def dataset_metadata(self) -> dict:
        return {
            "record_count": self._spell_document.get("record_count", len(self.load_spells())),
            "generated_at": self._spell_document.get("generated_at"),
            "source": self._spell_document.get("source"),
        }

    def _remove_stale_atomic_files(self) -> None:
        for path in self.root.glob(".state.json.*.tmp"):
            if path.is_file():
                path.unlink(missing_ok=True)

    def _migrate_state(self) -> None:
        """Accept early development state without carrying mutable indexes on."""

        state = self.load_state()
        changed = False
        for obsolete in ("imported_classes", "index_metadata"):
            if obsolete in state:
                del state[obsolete]
                changed = True
        for book in state.get("spellbooks", {}).values():
            if "summoning_feats" in book:
                del book["summoning_feats"]
                changed = True
        if changed:
            self.save_state(state)

    def _finish_interrupted_spellbook_deletes(self) -> None:
        spellbooks = self.load_state().get("spellbooks", {})
        for trash in self.spellbooks_dir.glob(".deleted-*"):
            if not trash.is_dir():
                continue
            for moved in trash.iterdir():
                if moved.name in spellbooks and not self.spellbook_dir(moved.name).exists():
                    os.replace(moved, self.spellbook_dir(moved.name))
            shutil.rmtree(trash, ignore_errors=True)

    def spellbook_dir(self, spellbook_id: str) -> Path:
        return self.spellbooks_dir / spellbook_id

    def create_spellbook(self, name: str) -> dict:
        name = " ".join(name.split()).strip()
        if not (1 <= len(name) <= 80):
            raise StoreError("Spellbook name must be between 1 and 80 characters")
        if any(ord(char) < 32 for char in name):
            raise StoreError("Spellbook name contains control characters")
        state = self.load_state()
        base = slugify(name)
        spellbook_id = base
        counter = 2
        while spellbook_id in state["spellbooks"]:
            spellbook_id = f"{base}-{counter}"
            counter += 1
        book = {
            "schema_version": 1,
            "id": spellbook_id,
            "name": name,
            "created_at": utc_now(),
            "renderer_version": RENDERER_VERSION,
            "batches": [],
            "open_batch": None,
            "content_page_count": 0,
            "exports": [],
        }
        state["spellbooks"][spellbook_id] = book
        self.spellbook_dir(spellbook_id).mkdir(parents=True, exist_ok=False)
        self.save_state(state)
        return deepcopy(book)

    def get_spellbook(self, spellbook_id: str) -> dict:
        try:
            return self.load_state()["spellbooks"][spellbook_id]
        except KeyError as exc:
            raise StoreError(f"Unknown spellbook: {spellbook_id}") from exc

    def update_spellbook(self, book: dict) -> None:
        state = self.load_state()
        if book["id"] not in state["spellbooks"]:
            raise StoreError(f"Unknown spellbook: {book['id']}")
        state["spellbooks"][book["id"]] = book
        self.save_state(state)

    def delete_spellbook(self, spellbook_id: str) -> dict:
        state = self.load_state()
        book = state["spellbooks"].pop(spellbook_id, None)
        if book is None:
            raise StoreError(f"Unknown spellbook: {spellbook_id}")
        book_dir = self.spellbook_dir(spellbook_id)
        trash = Path(tempfile.mkdtemp(prefix=".deleted-", dir=self.spellbooks_dir))
        moved = trash / spellbook_id
        try:
            if book_dir.exists():
                os.replace(book_dir, moved)
            self.save_state(state)
        except BaseException:
            if moved.exists():
                os.replace(moved, book_dir)
            trash.rmdir()
            raise
        shutil.rmtree(trash, ignore_errors=True)
        return book

    def begin_batch(self, spellbook_id: str) -> dict:
        book = self.get_spellbook(spellbook_id)
        if book["open_batch"] is not None:
            raise StoreError("This spellbook already has an open batch")
        batch_id = f"batch-{len(book['batches']) + 1:04d}"
        book["open_batch"] = {"id": batch_id, "created_at": utc_now(), "entities": []}
        self.update_spellbook(book)
        return book

    def add_open_entity(self, spellbook_id: str, entity: dict) -> dict:
        return self.add_open_entities(spellbook_id, [entity])

    def add_open_entities(self, spellbook_id: str, entities: list[dict]) -> dict:
        book = self.get_spellbook(spellbook_id)
        batch = book.get("open_batch")
        if not batch:
            raise StoreError("Begin a batch first")
        existing = {(item["kind"], item["id"]) for item in batch["entities"]}
        changed = False
        for entity in entities:
            key = (entity["kind"], entity["id"])
            if key not in existing:
                batch["entities"].append(entity)
                existing.add(key)
                changed = True
        if changed:
            self.update_spellbook(book)
        return book

    def remove_open_entity(self, spellbook_id: str, index: int) -> dict:
        book = self.get_spellbook(spellbook_id)
        batch = book.get("open_batch")
        if not batch:
            raise StoreError("There is no open batch")
        if not 0 <= index < len(batch["entities"]):
            raise StoreError("Invalid batch item")
        del batch["entities"][index]
        self.update_spellbook(book)
        return book
