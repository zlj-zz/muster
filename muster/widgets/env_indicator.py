"""Environment-check indicator strip for the left panel.

Shows coloured dots for each configured dependency (etcd, MySQL, Redis, etc.)
at the bottom of the service-tree column.
"""

from __future__ import annotations


from textual.widgets import Static

from ..models import MusterConfig


class EnvIndicator(Static):
    """Single-line environment dependency indicators.

    Refreshes alongside the app's env-check polling interval.

    Attributes:
        _config: MusterConfig holding env_checks and status_colors.
    """

    def __init__(self, config: MusterConfig, **kwargs) -> None:
        super().__init__(**kwargs)
        self._config = config

    def refresh_indicators(self, results: list[tuple[str, bool]]) -> None:
        """Update indicator dots with pre-computed check results.

        Args:
            results: List of ``(name, ok)`` pairs from :func:`check_env`.
        """
        indicators = []
        for name, ok in results:
            color = (
                self._config.status_colors.get("running", "#4ec9b0")
                if ok
                else self._config.status_colors.get("failed", "#f44747")
            )
            dot = "●" if ok else "○"
            indicators.append(f"[{color}]{dot} {name}[/{color}]")
        self.update("  ".join(indicators) if indicators else "")
