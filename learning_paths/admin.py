"""
Django Admin for learning_paths - Backward Compatibility Layer.

This module maintains backward compatibility by re-exporting all admin classes
from the feature-based admin modules.
"""

# Import everything from the admin package to trigger registrations
from .admin import *  # noqa: F401, F403

# Explicitly list exports for better IDE support
__all__ = [
    # Widgets & Utilities
    "CourseKeyDatalistWidget",
    "get_course_keys_choices",
    # Learning Paths
    "LearningPathAdmin",
    "LearningPathStepForm",
    "LearningPathStepInline",
    "AcquiredSkillInline",
    "RequiredSkillInline",
    "BulkEnrollUsersForm",
    # Skills
    "SkillAdmin",
    # Enrollments
    "EnrolledUsersAdmin",
    "EnrollmentAllowedAdmin",
    "EnrollmentAuditAdmin",
    "EnrollmentAuditInline",
    "EnrollmentAllowedAuditInline",
    # Group Enrollments
    "GroupCourseAssignmentAdmin",
    "GroupCourseEnrollmentAuditAdmin",
    "EnhancedGroupAdmin",
    "BulkAddUsersToGroupForm",
    "GroupCourseAssignmentInline",
    "GroupCourseEnrollmentAuditInline",
]
