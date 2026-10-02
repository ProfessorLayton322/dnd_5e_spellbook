from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .service import commit_open_batch, prefix_search
from .store import RuntimeStore
from .util import resolve_portable_path


PACKAGE_ROOT = Path(__file__).resolve().parent
EXPORT_LABELS = {"toc": "table of contents", "append": "new pages", "manifest": "manifest"}


def _export_filename(book_name: str, label: str, suffix: str) -> str:
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", book_name).strip(" .") or "spellbook"
    return f"{safe_name} - {label}{suffix}"


def _class_levels(spells: dict[str, dict]) -> dict[str, list[int]]:
    result: dict[str, set[int]] = {}
    for spell in spells.values():
        for class_name in spell.get("classes", []):
            result.setdefault(class_name, set()).add(spell["level"])
    return {name: sorted(levels) for name, levels in sorted(result.items(), key=lambda item: item[0].casefold())}


def create_app(runtime_dir: Path, bundled_spells: Path | None = None) -> FastAPI:
    app = FastAPI(title="D&D 5e Spellbook Builder")
    app.state.store = RuntimeStore(runtime_dir, bundled_spells=bundled_spells)
    templates = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))
    app.mount("/static", StaticFiles(directory=str(PACKAGE_ROOT / "static")), name="static")

    def redirect(book_id: str | None = None, message: str | None = None, error: str | None = None):
        params = []
        if book_id:
            params.append("book=" + quote(book_id))
        if message:
            params.append("message=" + quote(message))
        if error:
            params.append("error=" + quote(error))
        return RedirectResponse("/?" + "&".join(params), status_code=303)

    @app.get("/")
    def index(request: Request, book: str | None = None, message: str | None = None, error: str | None = None):
        store: RuntimeStore = app.state.store
        state = store.load_state()
        selected = state["spellbooks"].get(book) if book else next(iter(state["spellbooks"].values()), None)
        spells = store.load_spells()
        open_items = []
        if selected and selected.get("open_batch"):
            for item in selected["open_batch"]["entities"]:
                open_items.append({**item, "title": spells.get(item["id"], {}).get("name", item["id"])})
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "state": state,
                "selected": selected,
                "open_items": open_items,
                "class_levels": _class_levels(spells),
                "dataset": store.dataset_metadata(),
                "message": message,
                "error": error,
            },
        )

    @app.post("/spellbooks")
    def create_spellbook_route(name: str = Form(...)):
        try:
            created = app.state.store.create_spellbook(name)
            return redirect(created["id"], "Spellbook created")
        except Exception as exc:
            return redirect(error=str(exc))

    @app.post("/spellbooks/{book_id}/delete")
    def delete_spellbook_route(book_id: str):
        try:
            deleted = app.state.store.delete_spellbook(book_id)
            return redirect(message=f"Deleted spellbook {deleted['name']}")
        except Exception as exc:
            return redirect(book_id, error=str(exc))

    @app.post("/spellbooks/{book_id}/begin")
    def begin_route(book_id: str):
        try:
            app.state.store.begin_batch(book_id)
            return redirect(book_id, "Batch started")
        except Exception as exc:
            return redirect(book_id, error=str(exc))

    @app.post("/spellbooks/{book_id}/add-spell")
    def add_spell_route(book_id: str, spell_id: str = Form(...)):
        try:
            spells = app.state.store.load_spells()
            if spell_id not in spells:
                raise ValueError("Select a spell from the prefix suggestions")
            app.state.store.add_open_entity(book_id, {"kind": "spell", "id": spell_id})
            return redirect(book_id, f"Added {spells[spell_id]['name']}")
        except Exception as exc:
            return redirect(book_id, error=str(exc))

    @app.post("/spellbooks/{book_id}/add-class-level")
    def add_class_level_route(book_id: str, class_name: str = Form(...), level: int = Form(...)):
        try:
            spells = app.state.store.load_spells()
            matching = sorted(
                (
                    spell
                    for spell in spells.values()
                    if spell.get("level") == level
                    and any(value.casefold() == class_name.casefold() for value in spell.get("classes", []))
                ),
                key=lambda spell: spell.get("name_ru", spell["name"]).casefold(),
            )
            if not matching:
                raise ValueError("No spells found for that class and level")
            before = len(app.state.store.get_spellbook(book_id)["open_batch"]["entities"])
            app.state.store.add_open_entities(
                book_id,
                [{"kind": "spell", "id": spell["id"]} for spell in matching],
            )
            after = len(app.state.store.get_spellbook(book_id)["open_batch"]["entities"])
            return redirect(book_id, f"Added {after - before} {class_name} level {level} spells")
        except Exception as exc:
            return redirect(book_id, error=str(exc))

    @app.post("/spellbooks/{book_id}/remove/{index}")
    def remove_route(book_id: str, index: int):
        try:
            app.state.store.remove_open_entity(book_id, index)
            return redirect(book_id, "Removed batch item")
        except Exception as exc:
            return redirect(book_id, error=str(exc))

    @app.post("/spellbooks/{book_id}/commit")
    def commit_route(book_id: str):
        try:
            book = commit_open_batch(app.state.store, book_id)
            batch = book["batches"][-1]
            return redirect(book_id, f"Committed {batch['id']} as content pages {batch['page_start']}–{batch['page_end']}")
        except Exception as exc:
            return redirect(book_id, error=str(exc))

    @app.get("/api/spells")
    def spell_search(prefix: str = Query("", max_length=100)):
        return JSONResponse(prefix_search(app.state.store.load_spells(), prefix))

    @app.get("/spellbooks/{book_id}/files/{kind}")
    def file_route(book_id: str, kind: str):
        book = app.state.store.get_spellbook(book_id)
        book_dir = app.state.store.spellbook_dir(book_id)
        if kind == "full":
            path = book_dir / "full.pdf"
            label = "full spellbook"
        elif kind in {"toc", "append", "manifest"} and book["exports"]:
            last = book["exports"][-1]
            key = {"toc": "toc_pdf", "append": "append_pdf"}.get(kind)
            stored_path = last[key] if key else f"exports/{last['batch_id']}/manifest.json"
            path = resolve_portable_path(book_dir, stored_path)
            label = f"{last['batch_id']} {EXPORT_LABELS[kind]}"
        else:
            return JSONResponse({"error": "File not available"}, status_code=404)
        if not path.is_file() or book_dir.resolve() not in path.resolve().parents:
            return JSONResponse({"error": "File not available"}, status_code=404)
        return FileResponse(
            path,
            filename=_export_filename(book["name"], label, path.suffix),
            content_disposition_type="inline",
        )

    return app
