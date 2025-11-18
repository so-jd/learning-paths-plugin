"""
Django Admin for learning_paths - Modular Structure.

This module automatically imports and registers all admin classes
from feature-based admin modules.
"""

# Import all admin modules to trigger their @admin.register decorators
from . import enrollments  # noqa: F401
from . import group_enrollments  # noqa: F401
from . import learning_paths  # noqa: F401
from . import skills  # noqa: F401

# Export widgets for backward compatibility
from .widgets import CourseKeyDatalistWidget, get_course_keys_choices  # noqa: F401

# Export all admin classes for backward compatibility (if needed)
from .learning_paths import (
    AcquiredSkillInline,
    BulkEnrollUsersForm,
    LearningPathAdmin,
    LearningPathStepForm,
    LearningPathStepInline,
    RequiredSkillInline,
)
from .skills import SkillAdmin
from .enrollments import (
    EnrolledUsersAdmin,
    EnrollmentAllowedAdmin,
    EnrollmentAuditAdmin,
    EnrollmentAllowedAuditInline,
    EnrollmentAuditInline,
)
from .group_enrollments import (
    BulkAddUsersToGroupForm,
    EnhancedGroupAdmin,
    GroupCourseAssignmentAdmin,
    GroupCourseAssignmentInline,
    GroupCourseEnrollmentAuditAdmin,
    GroupCourseEnrollmentAuditInline,
)

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
