"""Safe natural-language automation service for the home dashboard."""

from .client import DashboardClient
from .engine import AutomationEngine
from .store import AutomationStore

__all__ = ["AutomationEngine", "AutomationStore", "DashboardClient"]
