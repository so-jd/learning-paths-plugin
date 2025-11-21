"""
Views for LearningPath - Backward Compatibility Layer.

This module maintains backward compatibility by re-exporting all views
from the feature-based view modules.
"""

# Learning Path Management
from .learning_paths import LearningPathAsProgramViewSet, LearningPathViewSet

# Progress & Grading
from .progress import LearningPathUserGradeView, LearningPathUserProgressView

# Enrollments
from .enrollments import (
    BulkEnrollView,
    GroupsListView,
    LearningPathCourseEnrollmentView,
    LearningPathEnrollmentView,
    ListEnrollmentsView,
)

# Group-based Enrollment
from .groups import (
    BulkEnrollGroupToCourseView,
    GroupCourseAssignmentViewSet,
    SyncGroupEnrollmentsView,
)

# Certificates
from .certificates import LearningPathCertificateStatusView

# Prerequisites
from .prerequisites import CoursePrerequisitesView

# Integration
from .integration import AllObjectTagsView

# Export all views for backward compatibility
__all__ = [
    # Learning Paths
    "LearningPathAsProgramViewSet",
    "LearningPathViewSet",
    # Progress & Grading
    "LearningPathUserProgressView",
    "LearningPathUserGradeView",
    # Enrollments
    "LearningPathEnrollmentView",
    "ListEnrollmentsView",
    "BulkEnrollView",
    "GroupsListView",
    "LearningPathCourseEnrollmentView",
    # Groups
    "GroupCourseAssignmentViewSet",
    "BulkEnrollGroupToCourseView",
    "SyncGroupEnrollmentsView",
    # Certificates
    "LearningPathCertificateStatusView",
    # Prerequisites
    "CoursePrerequisitesView",
    # Integration
    "AllObjectTagsView",
]
