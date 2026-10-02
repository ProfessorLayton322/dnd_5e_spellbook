from __future__ import annotations

from spellbook_builder.dndsu import SITEMAP_URL, crawl_spells, discover_spell_urls, parse_spell_page


def test_discovers_only_numeric_official_spell_urls():
    sitemap = """<?xml version="1.0"?><urlset xmlns="https://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://dnd.su/spells/2-second_spell/</loc></url>
    <url><loc>https://dnd.su/spells/1-first_spell/</loc></url>
    <url><loc>https://dnd.su/homebrew/spells/3-nope/</loc></url>
    <url><loc>https://dnd.su/spells/</loc></url>
    </urlset>"""
    assert discover_spell_urls(sitemap) == [
        "https://dnd.su/spells/1-first_spell/",
        "https://dnd.su/spells/2-second_spell/",
    ]


def test_parses_semantic_spell_card_with_lists_and_tables():
    html = """
    <div class="card" data-id="spells:42">
      <h2 class="card-title"><span data-copy="Тайный знак [Secret Mark]">Тайный знак</span><span class="source-plaque" title="Test Book">TB</span></h2>
      <div itemprop="articleBody"><ul class="params">
        <li class="size-type-alignment">1 уровень, прорицание (ритуал)</li>
        <li><strong>Время накладывания:</strong> 1 действие</li>
        <li><strong>Дистанция:</strong> Касание</li>
        <li><strong>Компоненты:</strong> В, С</li>
        <li><strong>Длительность:</strong> Концентрация, вплоть до 1 минуты</li>
        <li><strong>Классы:</strong> волшебник, друид TCE</li>
        <li class="subsection desc"><div itemprop="description">
          <p>Первый абзац.</p><ul><li>Первый эффект</li><li>Второй эффект</li></ul>
          <table><tr><th>Бросок</th><th>Эффект</th></tr><tr><td>1</td><td>Свет</td></tr></table>
        </div></li>
      </ul></div>
    </div>
    """
    spell = parse_spell_page(html, "https://dnd.su/spells/42-secret_mark/")
    assert spell["id"] == "dndsu-42"
    assert spell["name_ru"] == "Тайный знак"
    assert spell["name_en"] == "Secret Mark"
    assert spell["level"] == 1
    assert spell["school"] == "прорицание"
    assert spell["ritual"] is True
    assert spell["concentration"] is True
    assert spell["classes"] == ["волшебник", "друид"]
    assert [block["type"] for block in spell["content_blocks"]] == ["paragraph", "list", "table"]
    assert "Бросок: 1" in spell["tables"][0]
    assert spell["source_book"] == "Test Book"


def test_crawl_checkpoints_and_reuses_completed_records(tmp_path):
    urls = ["https://dnd.su/spells/1-first_spell/", "https://dnd.su/spells/2-second_spell/"]
    sitemap = "<urlset>" + "".join(f"<url><loc>{url}</loc></url>" for url in urls) + "</urlset>"

    def page(spell_id: int) -> str:
        return f"""
        <div class="card" data-id="spells:{spell_id}">
          <h2 class="card-title"><span data-copy="Тест {spell_id} [Test {spell_id}]">Тест</span></h2>
          <div itemprop="articleBody"><ul class="params">
            <li class="size-type-alignment">Заговор, воплощение</li>
            <li><strong>Классы:</strong> волшебник</li>
            <li class="subsection desc"><div itemprop="description"><p>Описание.</p></div></li>
          </ul></div>
        </div>"""

    class FakeFetcher:
        retries = 0

        def __init__(self):
            self.calls = []

        def get(self, url):
            self.calls.append(url)
            return sitemap if url == SITEMAP_URL else page(int(url.split("/")[4].split("-", 1)[0]))

    output = tmp_path / "spells.json"
    first = FakeFetcher()
    result = crawl_spells(first, output)
    assert result["record_count"] == 2
    assert first.calls == [SITEMAP_URL, *urls]

    second = FakeFetcher()
    resumed = crawl_spells(second, output)
    assert resumed["record_count"] == 2
    assert second.calls == [SITEMAP_URL]
