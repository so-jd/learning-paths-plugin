"""
Models package for learning_paths.

This package provides feature-based model organization while maintaining
backward compatibility with imports from learning_paths.models.
"""

# Import all models from feature modules
from .learning_paths import (
    LEVEL_CHOICES,
    LearningPath,
    LearningPathGradingCriteria,
    LearningPathManager,
    LearningPathStep,
)
from .skills import AcquiredSkill, LearningPathSkill, RequiredSkill, Skill
from .enrollments import (
    LearningPathEnrollment,
    LearningPathEnrollmentAllowed,
    LearningPathEnrollmentAudit,
)
from .groups import GroupCourseAssignment, GroupCourseEnrollmentAudit

# Export all models for backward compatibility
__all__ = [
    # Learning Paths
    "LEVEL_CHOICES",
    "LearningPath",
    "LearningPathManager",
    "LearningPathStep",
    "LearningPathGradingCriteria",
    # Skills
    "Skill",
    "LearningPathSkill",
    "RequiredSkill",
    "AcquiredSkill",
    # Enrollments
    "LearningPathEnrollment",
    "LearningPathEnrollmentAllowed",
    "LearningPathEnrollmentAudit",
    # Groups
    "GroupCourseAssignment",
    "GroupCourseEnrollmentAudit",
]
