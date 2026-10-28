"""Tests for the HelpOverlay modal screen."""

from __future__ import annotations

from muster.app import MusterApp
from muster.widgets import HelpOverlay


async def test_help_opens_and_closes(minimal_app):
    """? opens the overlay; escape returns to the main screen."""
    app = minimal_app
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpOverlay)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpOverlay)


async def test_help_lists_all_app_bindings(minimal_app):
    """Every visible app binding (including hidden ones) is listed."""
    app = minimal_app
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        overlay = app.screen
        assert isinstance(overlay, HelpOverlay)
        descriptions = {description for _, description in overlay.key_rows()}
        for binding in MusterApp.BINDINGS:
            if "help" in binding.action:
                continue
            assert binding.description in descriptions, (
                f"binding {binding.key!r} ({binding.description!r}) missing from help"
            )
