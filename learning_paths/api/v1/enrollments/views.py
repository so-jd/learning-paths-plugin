"""
Views for Learning Path enrollments.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db.models import Count, QuerySet
from django.shortcuts import get_object_or_404
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from rest_framework import generics, status
from rest_framework.exceptions import ParseError
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from learning_paths.compat import enroll_user_in_course
from learning_paths.keys import LearningPathKey
from learning_paths.models import (
    LearningPath,
    LearningPathEnrollment,
    LearningPathEnrollmentAllowed,
    LearningPathEnrollmentAudit,
)

from ..permissions import IsAdminOrSelf
from .serializers import LearningPathEnrollmentSerializer

logger = logging.getLogger(__name__)

User = get_user_model()


class LearningPathEnrollmentView(APIView):
    """
    API View to handle changes to LearningPathEnrollment model
    """

    permission_classes = [IsAuthenticated, IsAdminOrSelf]

    def _get_learning_path(self, learning_path_key_str: str) -> LearningPath:
        """
        Get the learning path and verify user has access to it.

        :raises: Http404 if the learning path is not found or user does not have access.
        """
        return get_object_or_404(
            LearningPath.objects.get_paths_visible_to_user(self.request.user),
            key=learning_path_key_str,
        )

    def get(self, request, learning_path_key_str: str):
        """Get the learning path of users.

        Staff/Admin can get all the active enrollments of the learning path.
        Learners can get their enrollments only.

        Query params:
            username (optional): When provided it returns the enrollment for
                the specified user.
        """
        learning_path = self._get_learning_path(learning_path_key_str)

        enrollments = LearningPathEnrollment.objects.filter(
            learning_path=learning_path,
            is_active=True
        ).select_related('user', 'learning_path')

        if request.user.is_staff:
            if username := request.query_params.get("username"):
                enrollments = enrollments.filter(user__username=username)
        else:
            enrollments = enrollments.filter(user=request.user)

        # Manually construct the response with user details
        data = []
        for enrollment in enrollments:
            data.append({
                'user': {
                    'id': enrollment.user.id,
                    'username': enrollment.user.username,
                    'email': enrollment.user.email,
                },
                'learning_path': {
                    'id': enrollment.learning_path.id,
                    'key': str(enrollment.learning_path.key),
                    'display_name': enrollment.learning_path.display_name,
                },
                'is_active': enrollment.is_active,
                'created': enrollment.created,
            })

        return Response(data)

    def post(self, request, learning_path_key_str: str):
        """Enroll learners in Learning Paths.

        Staff/Admin can enroll anyone with the username query param.
        Learners can enroll only themselves, and only if the learning path is not invite-only.

        Example payload::

            {
                "username": "user_1"
            }

        """
        learning_path = self._get_learning_path(learning_path_key_str)
        username = request.data.get("username")
        user = get_object_or_404(User, username=username) if username else request.user

        enrollment, created = LearningPathEnrollment.objects.get_or_create(learning_path=learning_path, user=user)
        if created:
            return Response(
                LearningPathEnrollmentSerializer(enrollment).data,
                status=status.HTTP_201_CREATED,
            )
        if enrollment.is_active:
            return Response({"detail": "Enrollment exists."}, status=status.HTTP_409_CONFLICT)

        enrollment.is_active = True
        enrollment.save()
        return Response(LearningPathEnrollmentSerializer(enrollment).data)

    def delete(self, request, learning_path_key_str: str):
        """
        Unenroll a learner from a learning path.

        Staff/admin can unenroll anyone with the username query param.
        Learners can self-unenroll if settings.LEARNING_PATHS_ALLOW_SELF_UNENROLLMENT is True.

        Example payload::

            {
                "username": "user_1"
            }

        """
        learning_path = self._get_learning_path(learning_path_key_str)
        username = request.data.get("username")
        user = get_object_or_404(User, username=username) if username else request.user

        enrollment = get_object_or_404(
            LearningPathEnrollment,
            learning_path=learning_path,
            is_active=True,
            user=user,
        )

        if not request.user.is_staff and not settings.LEARNING_PATHS_ALLOW_SELF_UNENROLLMENT:
            raise PermissionDenied

        enrollment.is_active = False
        enrollment.save()
        return Response(
            LearningPathEnrollmentSerializer(enrollment).data,
            status=status.HTTP_204_NO_CONTENT,
        )


class ListEnrollmentsView(APIView):
    """
    List Learning Path Enrollments.

    For staff, this returns enrollments from all learning paths for all users.
    For non-staff, this returns all enrollments for the current user.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get enrollments with full user and learning path details."""
        enrollments = LearningPathEnrollment.objects.select_related('user', 'learning_path').all()

        # Filter based on user role
        if not request.user.is_staff:
            enrollments = enrollments.filter(user=request.user)
        elif username := request.query_params.get("username"):
            enrollments = enrollments.filter(user__username=username)

        # Manually construct the response with user details
        data = []
        for enrollment in enrollments:
            data.append({
                'user': {
                    'id': enrollment.user.id,
                    'username': enrollment.user.username,
                    'email': enrollment.user.email,
                },
                'learning_path': {
                    'id': enrollment.learning_path.id,
                    'key': str(enrollment.learning_path.key),
                    'display_name': enrollment.learning_path.display_name,
                },
                'is_active': enrollment.is_active,
                'created': enrollment.created,
            })

        return Response(data)


class BulkEnrollView(APIView):
    """
    Bulk enrollment/unenrollment API for LearningPathEnrollment.
    """

    permission_classes = [IsAdminUser]

    @staticmethod
    def _process_input_data(request: Request) -> tuple[list[str], list[str], list[int]]:
        """Extract and validate input data from request."""
        from django.contrib.auth.models import Group

        data = request.data
        learning_paths_keys = data.get("learning_paths", "").split(",")
        emails_str = data.get("emails", "")
        group_ids_str = data.get("group_ids", "")

        emails = emails_str.split(",") if emails_str else []

        # Parse group IDs
        group_ids = []
        if group_ids_str:
            try:
                group_ids = [int(gid.strip()) for gid in group_ids_str.split(",") if gid.strip()]
            except ValueError:
                logger.warning("BulkEnrollView: Invalid group_ids format")

        # Fetch emails from groups
        if group_ids:
            groups = Group.objects.filter(id__in=group_ids).prefetch_related("user_set")
            group_user_emails = []
            for group in groups:
                group_user_emails.extend(group.user_set.values_list("email", flat=True))
            # Combine emails from input and groups, removing duplicates
            emails = list(set(list(emails) + group_user_emails))

        return learning_paths_keys, emails, group_ids

    @staticmethod
    def _validate_learning_paths(learning_paths_keys: list[str]) -> QuerySet[LearningPath]:
        """Validate learning path keys and return valid ones."""
        valid_learning_paths_keys = []
        for key in learning_paths_keys:
            try:
                LearningPathKey.from_string(key)
                valid_learning_paths_keys.append(key)
            except InvalidKeyError:
                logger.warning("BulkEnrollView: Invalid learning path key: %s", key)

        return LearningPath.objects.filter(key__in=valid_learning_paths_keys)

    @staticmethod
    def _create_audit_data(request: Request, state_transition: str) -> dict[str, str]:
        """Create audit data dictionary."""
        return {
            "enrolled_by": request.user,
            "reason": request.data.get("reason", ""),
            "org": request.data.get("org", ""),
            "role": request.data.get("role", ""),
            "state_transition": state_transition,
        }

    def _setup_bulk_operation(self, request: Request) -> tuple[QuerySet[LearningPath], QuerySet[User], list[str]]:
        """Common setup for bulk operations."""
        learning_paths_keys, emails, group_ids = self._process_input_data(request)
        learning_paths = self._validate_learning_paths(learning_paths_keys)
        existing_users = User.objects.filter(email__in=emails)

        return learning_paths, existing_users, emails

    def post(self, request: Request, *args, **kwargs) -> Response:
        """
        Bulk Enroll learners in Learning Paths.

        The "bulk enroll" API provides a way for the staff to enroll multiple learners
        in multiple learning paths at once.

        Example payload::

            {
                "learning_paths": "learning_path_1,learning_path_2",
                "emails": "user_1@example.com,user_2@example.com",
                "group_ids": "1,2,3",
                "reason": "Bulk enrollment for new cohort",
                "org": "organization_name",
                "role": "student"
            }

        `learning_paths` (str): A comma separated list of learning path IDs.
        `emails` (str, optional): A comma separated list of email addresses.
        `group_ids` (str, optional): A comma separated list of Django Group IDs.
        `reason` (str, optional): Reason for enrollment, used for audit.
        `org` (str, optional): Organization identifier, used for audit.
        `role` (str, optional): User role, used for audit.

        Note: You can provide emails, group_ids, or both. All members from specified groups
        will be enrolled along with any individually specified email addresses.

        * For existing users, it creates a new LearningPathEnrollment record, automatically
          enrolling them in the learning path. It also creates a LearningPathAllowed record
          to store the meta-data for audit later.
        * For non-existing users, it creates a new LearningPathEnrollmentAllowed record
          with just the email address, allowing them to get enrolled when they register.

        """
        learning_paths, existing_users, emails = self._setup_bulk_operation(request)
        non_existing_emails = set(emails) - set(u.email for u in existing_users)

        enrollments_created = []
        enrollment_allowed_created = []

        for learning_path in learning_paths:
            # Create LearningPathEnrollment for existing users
            for user in existing_users:
                enrollment = LearningPathEnrollment.objects.filter(user=user, learning_path=learning_path).first()
                enrolled_now = False
                audit_data = self._create_audit_data(request, LearningPathEnrollmentAudit.UNENROLLED_TO_ENROLLED)
                if enrollment:
                    if not enrollment.is_active:
                        enrollment.is_active = True
                        enrolled_now = True
                    else:
                        audit_data["state_transition"] = LearningPathEnrollmentAudit.ENROLLED_TO_ENROLLED
                else:
                    enrollment = LearningPathEnrollment(user=user, learning_path=learning_path)
                    enrolled_now = True

                # Set enrollment audit data that will be used by the post_save receiver.
                enrollment._audit = audit_data  # pylint: disable=protected-access
                enrollment.save()
                if enrolled_now:
                    enrollments_created.append(enrollment)

            # Create LearningPathEnrollmentAllowed for non-existing users
            for email in non_existing_emails:
                try:
                    validate_email(email)
                except ValidationError:
                    logger.warning("BulkEnrollView: Invalid email: %s", email)
                    continue
                allowed, created = LearningPathEnrollmentAllowed.objects.get_or_create(
                    email=email, learning_path=learning_path
                )
                if created or (not allowed.user and not allowed.is_active):
                    allowed.is_active = True
                    enrollment_allowed_created.append(allowed)

                audit_data = self._create_audit_data(request, LearningPathEnrollmentAudit.UNENROLLED_TO_ALLOWEDTOENROLL)
                allowed._audit = audit_data  # pylint: disable=protected-access
                allowed.save()

        return Response(
            {
                "enrollments_created": len(enrollments_created),
                "enrollment_allowed_created": len(enrollment_allowed_created),
            },
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request, *args, **kwargs) -> Response:
        """
        Bulk Unenroll learners from Learning Paths.

        The "bulk unenroll" API provides a way for the staff to unenroll multiple learners
        from multiple learning paths at once.

        Example payload::

            {
                "learning_paths": "learning_path_1,learning_path_2",
                "emails": "user_1@example.com,user_2@example.com",
                "group_ids": "1,2,3",
                "reason": "End of semester cleanup",
                "org": "organization_name",
                "role": "student"
            }

        `learning_paths` (str): A comma separated list of learning path IDs.
        `emails` (str, optional): A comma separated list of email addresses.
        `group_ids` (str, optional): A comma separated list of Django Group IDs.
        `reason` (str, optional): Reason for unenrollment, used for audit.
        `org` (str, optional): Organization identifier, used for audit.
        `role` (str, optional): User role, used for audit.

        Note: You can provide emails, group_ids, or both. All members from specified groups
        will be unenrolled along with any individually specified email addresses.

        * For existing users, it deactivates their LearningPathEnrollment records.
        * For emails with active LearningPathEnrollmentAllowed records, it deactivates those records.

        """
        learning_paths, existing_users, emails = self._setup_bulk_operation(request)

        enrollments_unenrolled = []
        enrollment_allowed_deactivated = []

        for learning_path in learning_paths:
            for user in existing_users:
                enrollment = LearningPathEnrollment.objects.filter(user=user, learning_path=learning_path).first()

                if enrollment:
                    if enrollment.is_active:
                        state_transition = LearningPathEnrollmentAudit.ENROLLED_TO_UNENROLLED
                        enrollment.is_active = False
                        enrollments_unenrolled.append(enrollment)
                    else:
                        state_transition = LearningPathEnrollmentAudit.UNENROLLED_TO_UNENROLLED
                    audit_data = self._create_audit_data(request, state_transition)
                    enrollment._audit = audit_data  # pylint: disable=protected-access
                    enrollment.save()

            for email in emails:
                try:
                    validate_email(email)
                except ValidationError:
                    logger.warning("BulkEnrollView: Invalid email: %s", email)
                    continue

                enrollment_allowed = LearningPathEnrollmentAllowed.objects.filter(
                    email=email,
                    learning_path=learning_path,
                ).first()

                if enrollment_allowed:
                    if enrollment_allowed.is_active:
                        state_transition = LearningPathEnrollmentAudit.ALLOWEDTOENROLL_TO_UNENROLLED
                        enrollment_allowed.is_active = False
                        enrollment_allowed_deactivated.append(enrollment_allowed)
                    else:
                        state_transition = LearningPathEnrollmentAudit.UNENROLLED_TO_UNENROLLED
                    audit_data = self._create_audit_data(request, state_transition)
                    enrollment_allowed._audit = audit_data  # pylint: disable=protected-access
                    enrollment_allowed.save()

        return Response(
            {
                "enrollments_unenrolled": len(enrollments_unenrolled),
                "enrollment_allowed_deactivated": len(enrollment_allowed_deactivated),
            },
            status=status.HTTP_204_NO_CONTENT,
        )


class GroupsListView(generics.ListAPIView):
    """
    List all Django groups for bulk enrollment purposes.

    Returns a list of all available Django Auth Groups that can be used
    for bulk enrollment in learning paths.

    Permissions: Admin users only
    """

    permission_classes = [IsAdminUser]

    def get(self, request, *args, **kwargs):
        """List all groups with their ID, name, and member count."""
        from django.contrib.auth.models import Group

        groups = Group.objects.all().annotate(
            member_count=Count('user')
        ).order_by('name')

        data = [
            {
                'id': group.id,
                'name': group.name,
                'member_count': group.member_count,
            }
            for group in groups
        ]

        return Response(data, status=status.HTTP_200_OK)


class LearningPathCourseEnrollmentView(APIView):
    """API View to enroll a user in a course that's part of a learning path."""

    permission_classes = [IsAuthenticated, IsAdminOrSelf]

    def _get_enrolled_learning_path(self, learning_path_key_str: str) -> LearningPath:
        """
        Get the learning path and verify the user has access and is enrolled.

        :raises: Http404 if the learning path is not found or the user does not have access.
        """
        return get_object_or_404(
            LearningPath.objects.get_paths_visible_to_user(self.request.user).filter(enrollment_date__isnull=False),
            key=learning_path_key_str,
        )

    def post(self, request, learning_path_key_str: str, course_key_str: str):
        """
        Enroll a user in a course that's part of a learning path.

        The user must be enrolled in the learning path, and the course must be a step in the path.
        """
        learning_path = self._get_enrolled_learning_path(learning_path_key_str)
        course_key = CourseKey.from_string(course_key_str)

        if not learning_path.steps.filter(course_key=course_key).exists():
            raise ParseError("The course is not part of this learning path.")

        if enroll_user_in_course(request.user, course_key):
            return Response(
                {"detail": "User successfully enrolled in the course."},
                status=status.HTTP_201_CREATED,
            )
        else:
            raise ParseError("Failed to enroll the user in the course.")
