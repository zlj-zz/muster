"""YAML file list for the yaml tab's left panel.

Renders a simple :class:`Tree` whose leaf nodes are YAML file names.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from textual import on
from textual.message import Message
from textual.widgets import Tree


class FileList(Tree):
    """List of YAML configuration files.

    Attributes:
        files: List of file paths or names to display.
    """

    def __init__(
        self,
        files: List[str],
        **kwargs,
    ) -> None:
        super().__init__("Files", **kwargs)
        self.files = files
        self._node_map: Dict[str, Tree.TreeNode] = {}
        self.show_root = False
        self.guide_depth = 2
        self.border_title = "Files"
        self._build_tree()

    def _build_tree(self) -> None:
        """Populate the tree with file nodes."""
        for name in self.files:
            leaf = self.root.add_leaf(name, data=name)
            self._node_map[name] = leaf

    @property
    def current_file(self) -> Optional[str]:
        """Return the file path of the currently highlighted node."""
        node = self.cursor_node
        if node and isinstance(node.data, str):
            return node.data
        return None

    @on(Tree.NodeHighlighted)
    def on_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """Bubble file selection events up to the App."""
        if isinstance(event.node.data, str):
            self.post_message(self.FileHighlighted(event.node.data))

    class FileHighlighted(Message):
        """Message sent when a file leaf is highlighted."""

        def __init__(self, file_path: str) -> None:
            self.file_path = file_path
            super().__init__()
