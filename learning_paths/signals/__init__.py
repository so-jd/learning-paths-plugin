"""
Signal handlers for learning_paths - Modular Structure.

This package organizes signal handlers by feature domain for better
maintainability and clarity.
"""

# Import all signal modules to register their handlers
from . import enrollments  # noqa: F401
from . import group_membership  # noqa: F401
from . import milestones  # noqa: F401

# The milestones module auto-connects its signals on import

__all__ = [
    "enrollments",
    "group_membership",
    "milestones",
]
