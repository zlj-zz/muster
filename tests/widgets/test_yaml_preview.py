"""Tests for YamlPreview widget."""

from __future__ import annotations

from muster.widgets.yaml_preview import YamlPreview
from tests.conftest import WidgetTestApp


class TestYamlPreview:
    """File preview rendering."""

    async def test_set_file_reads_content(self, tmp_path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("name: api\nport: 8080\n", encoding="utf-8")

        preview = YamlPreview()
        app = WidgetTestApp(preview)
        async with app.run_test() as pilot:
            preview = app.query_one(YamlPreview)
            preview.current_file = str(yaml_file)
            await pilot.pause()
            text_area = preview.query_one("#yaml-text")
            assert "name: api" in text_area.text
            assert "port: 8080" in text_area.text
            title = preview.query_one("#yaml-title")
            assert str(yaml_file) in str(title.render())

    async def test_set_none_clears(self):
        preview = YamlPreview()
        app = WidgetTestApp(preview)
        async with app.run_test() as pilot:
            preview = app.query_one(YamlPreview)
            preview.current_file = str(__file__)
            await pilot.pause()
            preview.current_file = None
            await pilot.pause()
            text_area = preview.query_one("#yaml-text")
            assert text_area.text == ""
            title = preview.query_one("#yaml-title")
            assert "Preview" in str(title.render())

    async def test_missing_file_shows_error(self, tmp_path):
        missing = tmp_path / "does-not-exist.yaml"
        preview = YamlPreview()
        app = WidgetTestApp(preview)
        async with app.run_test() as pilot:
            preview = app.query_one(YamlPreview)
            preview.current_file = str(missing)
            await pilot.pause()
            text_area = preview.query_one("#yaml-text")
            assert "Failed to read" in text_area.text
