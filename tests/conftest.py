from __future__ import annotations

import json
from pathlib import Path

import pytest


def sample_spell(
    spell_id: str = "dndsu-1",
    numeric_id: int = 1,
    name_ru: str = "Огненная искра",
    name_en: str = "Fire Spark",
    level: int = 1,
    classes: list[str] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "parser_version": 1,
        "id": spell_id,
        "numeric_id": numeric_id,
        "name": f"{name_ru} [{name_en}]",
        "name_ru": name_ru,
        "name_en": name_en,
        "normalized_name": f"{name_ru.casefold()} {name_en.casefold()}",
        "level": level,
        "school": "воплощение",
        "ritual": False,
        "concentration": False,
        "casting_time": "1 действие",
        "range": "60 футов",
        "components": "В, С",
        "duration": "Мгновенная",
        "classes": classes or ["волшебник"],
        "subclasses": [],
        "parameters": {
            "Время накладывания": "1 действие",
            "Дистанция": "60 футов",
            "Компоненты": "В, С",
            "Длительность": "Мгновенная",
            "Классы": ", ".join(classes or ["волшебник"]),
        },
        "content_blocks": [
            {
                "type": "paragraph",
                "text": "Короткое описание заклинания с кириллическим текстом.",
            }
        ],
        "description": "Короткое описание заклинания с кириллическим текстом.",
        "tables": [],
        "source_book": "Test Source",
        "source_code": "TEST",
        "source_url": f"https://dnd.su/spells/{numeric_id}-test/",
        "fetched_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def bundled_spells(tmp_path: Path) -> Path:
    first = sample_spell()
    second = sample_spell("dndsu-2", 2, "Ледяная игла", "Ice Needle", 2, ["волшебник", "друид"])
    path = tmp_path / "spells.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "https://dnd.su/spells/",
                "generated_at": "2026-01-01T00:00:00+00:00",
                "record_count": 2,
                "records": {first["id"]: first, second["id"]: second},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path
