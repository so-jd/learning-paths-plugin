"""
Learning Paths views and serializers - core learning path management.
"""

from .views import LearningPathAsProgramViewSet, LearningPathViewSet
from .serializers import (
    LearningPathAsProgramSerializer,
    LearningPathDetailSerializer,
    LearningPathListSerializer,
    LearningPathStepSerializer,
    LearningPathWriteSerializer,
)
from .skills_serializers import (
    AcquiredSkillSerializer,
    RequiredSkillSerializer,
    SkillSerializer,
)

__all__ = [
    # Views
    "LearningPathAsProgramViewSet",
    "LearningPathViewSet",
    # Serializers
    "LearningPathAsProgramSerializer",
    "LearningPathDetailSerializer",
    "LearningPathListSerializer",
    "LearningPathStepSerializer",
    "LearningPathWriteSerializer",
    # Skills Serializers
    "AcquiredSkillSerializer",
    "RequiredSkillSerializer",
    "SkillSerializer",
]
