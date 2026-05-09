"""Left-panel service tree with dynamic groups.

Renders a ``Tree`` widget whose root nodes are configured groups (domain,
aggregation, api, etc.) and whose leaf nodes are the actual services.  Each
leaf shows a coloured status dot, the service name, and its port.
"""

from rich.style import Style
from rich.text import Text
from textual import on
from textual.message import Message
from textual.widgets import Tree

from ..models import Group, Service, Status


class ServiceTree(Tree):
    """Hierarchical service tree grouped by configured groups.

    Attributes:
        services: Current list of services to render (filtered by group).
        groups: Group definitions for headers and ordering.
        status_colors: Mapping from status value to hex colour.
    """

    def __init__(
        self,
        services: list[Service],
        groups: list[Group],
        status_colors: dict[str, str],
        **kwargs,
    ) -> None:
        super().__init__("Services", **kwargs)
        self.services = services
        self.groups = groups
        self.status_colors = status_colors
        self._node_map: dict[str, Tree.TreeNode] = {}
        self.show_root = False
        self.guide_depth = 2
        self.border_title = "Services"
        self._build_tree()

    def _build_tree(self) -> None:
        """Populate the tree from ``self.services`` and ``self.groups``."""
        sorted_groups = sorted(self.groups, key=lambda g: g.order)

        for group in sorted_groups:
            layer_svcs = [s for s in self.services if s.group == group.id]
            if not layer_svcs:
                continue
            label = Text.assemble(
                ("▸ ", Style(color=group.color)),
                (group.label, Style(color=group.color, bold=True, underline=True)),
            )
            group_node = self.root.add(label, expand=True)
            for svc in layer_svcs:
                leaf = group_node.add_leaf(self._svc_label(svc), data=svc)
                self._node_map[svc.name] = leaf

    def rebuild(self) -> None:
        """Clear and rebuild the entire tree."""
        self._node_map.clear()
        for child in list(self.root.children):
            child.remove()
        self._build_tree()

    def _svc_label(self, svc: Service) -> Text:
        """Build the Rich ``Text`` label for a service leaf node.

        Args:
            svc: Service to render.

        Returns:
            A ``Text`` instance with status dot, name, and port.
        """
        status_color = self.status_colors.get(svc.status.value, "#6e7681")
        text = Text()
        # 2-space gap after dot so it does not visually merge with the name.
        text.append("● ", Style(color=status_color))
        text.append(svc.name)
        if svc.port:
            # 2-space gap before port, dim but visible on dark backgrounds.
            text.append(" ", Style(color="#3e4451"))
            text.append(f":{svc.port}", Style(color="#6e7681"))
        return text

    def refresh_node(self, svc: Service) -> None:
        """Re-render the label for a single service node.

        Args:
            svc: Service whose node should be refreshed.
        """
        node = self._node_map.get(svc.name)
        if node:
            node.set_label(self._svc_label(svc))

    @property
    def current_service(self) -> Service | None:
        """Return the service attached to the currently highlighted node."""
        node = self.cursor_node
        if node and isinstance(node.data, Service):
            return node.data
        return None

    def select_service(self, svc_name: str) -> None:
        """Programmatically select a service node.

        Args:
            svc_name: Name of the service to select.
        """
        node = self._node_map.get(svc_name)
        if node:
            self.select_node(node)

    def highlight_service(self, svc_name: str) -> None:
        """Move the cursor to a service without firing a selection event.

        Args:
            svc_name: Name of the service to highlight.
        """
        node = self._node_map.get(svc_name)
        if node:
            self.move_cursor(node)

    @on(Tree.NodeHighlighted)
    def on_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """Bubble service selection events up to the App."""
        if isinstance(event.node.data, Service):
            self.post_message(self.ServiceHighlighted(event.node.data))

    class ServiceHighlighted(Message):
        """Message sent when a service leaf is highlighted."""

        def __init__(self, service: Service) -> None:
            self.service = service
            super().__init__()
