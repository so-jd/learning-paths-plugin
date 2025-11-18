"""
Views for Learning Path core management.
"""

import logging

from opaque_keys import InvalidKeyError
from rest_framework import viewsets
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from core.models import LearningPath

from .serializers import (
    LearningPathAsProgramSerializer,
    LearningPathDetailSerializer,
    LearningPathListSerializer,
    LearningPathWriteSerializer,
)

logger = logging.getLogger(__name__)


class LearningPathAsProgramViewSet(viewsets.ReadOnlyModelViewSet):
    """
    This viewset exposes LearningPaths as Programs to be ingested
    by the course-discovery's refresh_course_metadata command.
    URL is: GET <LMS_URL>/api/v1/programs
    The command makes use of the ProgramsApiDataLoader.
    https://github.com/openedx/course-discovery/blob/d6a57fd69479b3d5f5afb682d2668b58503a6af6/course_discovery/apps/course_metadata/data_loaders/api.py#L843
    """

    permission_classes = (IsAuthenticated,)
    serializer_class = LearningPathAsProgramSerializer
    pagination_class = PageNumberPagination

    def get_queryset(self):
        """Get the learning paths visible to the current user."""
        return LearningPath.objects.get_paths_visible_to_user(self.request.user)


class LearningPathViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing learning paths.

    - List and retrieve: Available to authenticated users (respecting visibility rules)
    - Create, update, delete: Available to admin users only
    """

    pagination_class = PageNumberPagination
    lookup_field = "key"

    def get_permissions(self):
        """
        Set permissions based on action.
        - Read operations (list, retrieve): IsAuthenticated
        - Write operations (create, update, partial_update, destroy): IsAdminUser
        """
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def get_queryset(self):
        """
        Get all learning paths and prefetch the related data.
        """
        user = self.request.user

        # For write operations, admins should see all paths
        if self.action in ["update", "partial_update", "destroy"] and user.is_staff:
            return LearningPath.objects.all().prefetch_related("steps", "grading_criteria")

        # For read operations, use visibility rules
        queryset = LearningPath.objects.get_paths_visible_to_user(user).prefetch_related(
            "steps",
            "grading_criteria",
        )
        return queryset

    def get_serializer_class(self):
        """
        Use different serializers for different actions.
        """
        if self.action in ["create", "update", "partial_update"]:
            return LearningPathWriteSerializer
        elif self.action == "list":
            return LearningPathListSerializer
        return LearningPathDetailSerializer

    def get_object(self):
        """Gracefully handle an invalid learning path key format."""
        try:
            return super().get_object()
        except InvalidKeyError as exc:
            raise NotFound("Invalid learning path key format.") from exc
