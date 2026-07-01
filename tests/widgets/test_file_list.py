"""Tests for FileList widget."""

from __future__ import annotations

from muster.widgets.file_list import FileList
from tests.conftest import WidgetTestApp, capture_messages


class TestFileList:
    """YAML file list behaviour."""

    async def test_build_tree_creates_leaf_nodes(self):
        app = WidgetTestApp(FileList(["svc.yaml", "db.yaml"]))
        async with app.run_test() as pilot:
            file_list = app.query_one(FileList)
            await pilot.pause()
            assert len(file_list.root.children) == 2
            assert file_list.root.children[0].label.plain == "svc.yaml"

    async def test_current_file_returns_highlighted_name(self):
        app = WidgetTestApp(FileList(["svc.yaml", "db.yaml"]))
        async with app.run_test() as pilot:
            file_list = app.query_one(FileList)
            file_list.select_node(file_list.root.children[1])
            await pilot.pause()
            assert file_list.current_file == "db.yaml"

    async def test_current_file_none_when_no_selection(self):
        app = WidgetTestApp(FileList([]))
        async with app.run_test() as pilot:
            file_list = app.query_one(FileList)
            await pilot.pause()
            assert file_list.current_file is None

    async def test_highlight_posts_file_highlighted_message(self):
        app = WidgetTestApp(FileList(["svc.yaml"]))
        async with app.run_test() as pilot:
            file_list = app.query_one(FileList)
            messages = capture_messages(file_list, FileList.FileHighlighted)
            file_list.select_node(file_list.root.children[0])
            await pilot.pause()
            assert len(messages) == 1
            assert messages[0].file_path == "svc.yaml"
