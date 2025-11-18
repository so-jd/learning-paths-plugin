"""
Database models for learning_paths.

This module maintains backward compatibility by re-exporting all models
from the feature-based models package.
"""

# Re-export everything from the models package for backward compatibility
from .models import *  # noqa: F401, F403

# Explicitly list what's available for better IDE support
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
