"""
Serializer for LearningPath - Backward Compatibility Layer.

This module maintains backward compatibility by re-exporting all serializers
from the feature-based serializer modules.
"""

# Learning Path Management
from .learning_paths import (
    LearningPathAsProgramSerializer,
    LearningPathDetailSerializer,
    LearningPathListSerializer,
    LearningPathStepSerializer,
    LearningPathWriteSerializer,
)

# Skills
from .learning_paths.skills_serializers import (
    AcquiredSkillSerializer,
    RequiredSkillSerializer,
    SkillSerializer,
)

# Progress & Grading
from .progress import LearningPathGradeSerializer, LearningPathProgressSerializer

# Enrollments
from .enrollments import LearningPathEnrollmentSerializer

# Groups
from .groups import GroupCourseAssignmentSerializer, GroupCourseEnrollmentAuditSerializer

# Certificates
from .certificates import LearningPathCertificateStatusSerializer

# Export all serializers for backward compatibility
__all__ = [
    # Learning Path Management
    "LearningPathAsProgramSerializer",
    "LearningPathStepSerializer",
    "LearningPathListSerializer",
    "LearningPathDetailSerializer",
    "LearningPathWriteSerializer",
    # Skills
    "SkillSerializer",
    "RequiredSkillSerializer",
    "AcquiredSkillSerializer",
    # Progress & Grading
    "LearningPathProgressSerializer",
    "LearningPathGradeSerializer",
    # Enrollments
    "LearningPathEnrollmentSerializer",
    # Groups
    "GroupCourseAssignmentSerializer",
    "GroupCourseEnrollmentAudit Serializer",
    # Certificates
    "LearningPathCertificateStatusSerializer",
]
