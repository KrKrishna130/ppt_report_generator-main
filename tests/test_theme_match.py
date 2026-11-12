import asyncio
import json
import math
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.services.design import apply_theme
from app.services.theme_match import ASSETS, load_index, match_background
from app.temporal import activities


def test_all_images_are_indexed():
    rows = load_index()["images"]
    assert len(rows) == 96
    assert len({row["category"] for row in rows}) == 24
    assert {ASSETS / row["image"] for row in rows} == set(ASSETS.glob("*/*.jpeg"))
    for row in rows:
        assert math.isclose(sum(v * v for v in row["vector"].values()), 1.0)


@pytest.mark.parametrize("request_data, category, filename", [
    ({"prompt": "Create a presentation on the History of Terrorism in India"}, "14-", None),
    ({"text": {"content": "A coral reef underwater marine habitat"}}, "23-", "02.jpeg"),
    ({"text": {"messages": [{"content": "An army armored vehicle on a rocky hill"}]}},
     "02-", "army.jpeg"),
    ({"prompt": "Describe your deck: university library with bookshelves"}, "19-",
     "university_library.jpeg"),
])
def test_selects_background_from_all_input_types(request_data, category, filename):
    match = match_background(request_data, {})
    assert match["category"].startswith(category)
    assert 0 < match["score"] <= 1
    if filename:
        assert match["image"].endswith("/" + filename)


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("designed", [True, False])
def test_export_flag_and_cached_theme(tmp_path, monkeypatch, enabled, designed):
    monkeypatch.setattr(activities.settings, "output_dir", str(tmp_path))
    monkeypatch.setattr(activities.settings, "enable_theme_background_matching", enabled)
    theme = apply_theme({}, {"design_theme": "corporate_blue"}, "") if designed else {
        "background": "#FFFFFF"
    }
    request = {"prompt": "History of terrorism in India", "options": {"output": ["pptx"]}}
    theme["background_match"] = match_background({"prompt": "ocean"}, {})
    slides = [{"title": "History", "layout_variant": "hero" if designed else "title"},
              {"title": "Overview", "layout_variant": "bullets"}]

    result = asyncio.run(activities.render_outputs("job", request, {}, theme, [], slides, []))
    manifest = json.loads(Path(result["files"]["manifest"]).read_text(encoding="utf-8"))
    assert ("background_match" in manifest["theme"]) == enabled
    assert ("background_match" in result) == enabled
    if enabled:
        assert result["background_match"]["category"].startswith("14-")
    deck = Presentation(result["files"]["pptx"])
    assert len(deck.slides) == 2
    for slide in deck.slides:
        first = slide.shapes[0]
        assert (first.shape_type == MSO_SHAPE_TYPE.PICTURE and first.width == deck.slide_width) == enabled
        assert any(shape.has_text_frame for shape in slide.shapes)
