"""Environment check list for the env tab's left panel.

Renders a :class:`Tree` whose leaf nodes represent configured environment
checks (etcd, MySQL, Redis, etc.) with a coloured status dot and address.
"""

from __future__ import annotations


from rich.style import Style
from rich.text import Text
from textual import on
from textual.message import Message
from textual.widgets import Tree

from ..models import EnvCheck, MusterConfig


class EnvList(Tree):
    """List of environment checks with status indicators.

    Attributes:
        env_checks: List of checks to render.
        status_colors: Mapping of status value to hex colour.
    """

    def __init__(
        self,
        config: MusterConfig,
        **kwargs,
    ) -> None:
        super().__init__("Environment", **kwargs)
        self.env_checks = config.env_checks
        self.status_colors = config.status_colors
        self._node_map: dict[str, Tree.TreeNode] = {}
        self.show_root = False
        self.guide_depth = 2
        self.border_title = "Environment"
        self._build_tree()

    def _build_tree(self) -> None:
        """Populate the tree with environment check nodes."""
        for ec in self.env_checks:
            label = self._env_label(ec, ok=None)
            leaf = self.root.add_leaf(label, data=ec)
            self._node_map[ec.name] = leaf

    def _env_label(self, ec: EnvCheck, ok: bool | None) -> Text:
        """Build the Rich ``Text`` label for an environment check node.

        Args:
            ec: Environment check to render.
            ok: Pass/fail status, or ``None`` for unknown.

        Returns:
            A ``Text`` instance with status dot, name, and address.
        """
        running_color = self.status_colors.get("running", "#98c379")
        failed_color = self.status_colors.get("failed", "#e06c75")
        dim_color = "#5c6370"

        if ok is True:
            dot_color = running_color
            result = "ok"
        elif ok is False:
            dot_color = failed_color
            result = "fail"
        else:
            dot_color = dim_color
            result = "..."

        addr = f"{ec.host or '127.0.0.1'}:{ec.port}" if ec.port else (ec.host or "")

        text = Text()
        text.append("● ", Style(color=dot_color))
        text.append(ec.name)
        if addr:
            text.append(f"  {addr}", Style(color="#4a4a5c"))
        text.append(f"  {result}", Style(color=dim_color))
        return text

    def refresh_checks(self, results: list[tuple[str, bool]]) -> None:
        """Update node labels with fresh check results.

        Args:
            results: List of ``(name, ok)`` pairs from :func:`check_env`.
        """
        for name, ok in results:
            if getattr(self, "_last_results", {}).get(name) == ok:
                continue
            self._last_results = getattr(self, "_last_results", {})
            self._last_results[name] = ok
            node = self._node_map.get(name)
            if node and isinstance(node.data, EnvCheck):
                node.set_label(self._env_label(node.data, ok))

    @property
    def current_env(self) -> EnvCheck | None:
        """Return the env check attached to the currently highlighted node."""
        node = self.cursor_node
        if node and isinstance(node.data, EnvCheck):
            return node.data
        return None

    @on(Tree.NodeHighlighted)
    def on_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """Bubble env selection events up to the App."""
        if isinstance(event.node.data, EnvCheck):
            self.post_message(self.EnvHighlighted(event.node.data))

    class EnvHighlighted(Message):
        """Message sent when an env check leaf is highlighted."""

        def __init__(self, env_check: EnvCheck) -> None:
            self.env_check = env_check
            super().__init__()
