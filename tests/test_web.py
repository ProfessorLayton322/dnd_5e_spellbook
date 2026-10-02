from __future__ import annotations

from fastapi.testclient import TestClient

from spellbook_builder.web import create_app


def test_web_builds_batch_from_bundled_spells(tmp_path, bundled_spells):
    app = create_app(tmp_path / "runtime", bundled_spells)
    client = TestClient(app)

    page = client.get("/")
    assert page.status_code == 200
    assert "2</b> Russian D&amp;D 5e spells" in page.text

    created = client.post("/spellbooks", data={"name": "Web Book"}, follow_redirects=False)
    assert created.status_code == 303
    book_id = "web-book"
    client.post(f"/spellbooks/{book_id}/begin")

    search = client.get("/api/spells", params={"prefix": "Fire"})
    assert search.json()[0]["id"] == "dndsu-1"
    client.post(f"/spellbooks/{book_id}/add-spell", data={"spell_id": "dndsu-1"})
    committed = client.post(f"/spellbooks/{book_id}/commit", follow_redirects=False)
    assert committed.status_code == 303
    assert client.get(f"/spellbooks/{book_id}/files/full").status_code == 200
    assert client.get(f"/spellbooks/{book_id}/files/append").content.startswith(b"%PDF")
