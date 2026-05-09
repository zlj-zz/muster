"""Activity bar with vertical tabs for switching views.

Provides an ActivityBar container and ActivityTab widgets that work together
to implement a VS Code-style activity bar on the far left of the TUI.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static
from rich.text import Text


class ActivityTab(Static):
    """A single clickable tab in the activity bar.

    Displays an icon character and a short label stacked vertically.
    When clicked, posts a :class:`TabClicked` message.

    Attributes:
        tab_id: Identifier string (e.g. ``"svc"``).
    """

    DEFAULT_CSS = """
    ActivityTab {
        width: 100%;
        height: 4;
        content-align: center middle;
        color: #5c6370;
        text-style: none;
        border-left: inner #21252b;
        padding-left: 1;
    }
    ActivityTab:hover {
        background: #2c313c;
    }
    ActivityTab.active {
        background: #282c34;
        color: #e5a23e;
        text-style: bold;
        border-left: inner #e5a23e;
    }
    """

    def __init__(self, tab_id: str, icon: str, label: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.tab_id = tab_id
        self._icon = icon
        self._label = label

    def render(self) -> Text:
        """Return a vertically-stacked icon + label."""
        text = Text()
        text.append(self._icon, style="bold")
        text.append("\n")
        text.append(self._label, style="dim")
        return text

    def on_click(self) -> None:
        """Post a TabClicked message when the user clicks the tab."""
        self.post_message(self.TabClicked(self.tab_id))

    class TabClicked(Message):
        """Message sent when an activity tab is clicked.

        Attributes:
            tab_id: The ``tab_id`` of the clicked tab.
        """

        def __init__(self, tab_id: str) -> None:
            self.tab_id = tab_id
            super().__init__()


class ActivityBar(Vertical):
    """Vertical activity bar with tab switching.

    Manages a set of :class:`ActivityTab` widgets and exposes a reactive
    ``active_tab`` property that drives CSS styling.

    Attributes:
        active_tab: Currently active tab identifier.
    """

    DEFAULT_CSS = """
    ActivityBar {
        width: 8;
        height: 1fr;
        background: #21252b;
        border-right: solid #1a1d23;
        padding: 1 0;
    }
    """

    active_tab: reactive[str] = reactive("svc")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        """Yield the three default tabs."""
        yield ActivityTab("svc", "■", "svc", id="tab-svc")
        yield ActivityTab("env", "●", "env", id="tab-env")
        yield ActivityTab("yaml", "☰", "yaml", id="tab-yaml")

    def watch_active_tab(self, tab_id: str) -> None:
        """Update the ``active`` CSS class on child tabs."""
        for child in self.query(ActivityTab):
            if child.tab_id == tab_id:
                child.add_class("active")
            else:
                child.remove_class("active")
