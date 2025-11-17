"""
Views for LearningPath.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db.models import Count, QuerySet
from django.shortcuts import get_object_or_404
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from rest_framework import generics, status, viewsets
from rest_framework.exceptions import NotFound, ParseError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from learning_paths.api.v1.serializers import (
    GroupCourseAssignmentSerializer,
    GroupCourseEnrollmentAuditSerializer,
    LearningPathAsProgramSerializer,
    LearningPathDetailSerializer,
    LearningPathEnrollmentSerializer,
    LearningPathGradeSerializer,
    LearningPathListSerializer,
    LearningPathProgressSerializer,
    LearningPathWriteSerializer,
)
from learning_paths.compat import enroll_user_in_course
from learning_paths.keys import LearningPathKey
from learning_paths.models import (
    GroupCourseAssignment,
    GroupCourseEnrollmentAudit,
    LearningPath,
    LearningPathEnrollment,
    LearningPathEnrollmentAllowed,
    LearningPathEnrollmentAudit,
)

from .filters import AdminOrSelfFilterBackend
from .permissions import IsAdminOrSelf
from .utils import get_aggregate_progress

logger = logging.getLogger(__name__)

User = get_user_model()


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


class LearningPathUserProgressView(APIView):
    """
    API view to return the aggregate progress of a user in a learning path.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request, learning_path_key_str: str):
        """
        Fetch the learning path progress
        """
        learning_path = get_object_or_404(
            LearningPath.objects.get_paths_visible_to_user(self.request.user),
            key=learning_path_key_str,
        )

        progress = get_aggregate_progress(request.user, learning_path)
        required_completion = None
        try:
            grading_criteria = learning_path.grading_criteria
            required_completion = grading_criteria.required_completion
        except ObjectDoesNotExist:
            pass

        data = {
            "learning_path_key": learning_path_key_str,
            "progress": progress,
            "required_completion": required_completion,
        }

        serializer = LearningPathProgressSerializer(data=data)
        if serializer.is_valid():
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LearningPathUserGradeView(APIView):
    """
    API view to return the aggregate grade of a user in a learning path.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request, learning_path_key_str: str):
        """
        Fetch learning path grade
        """

        learning_path = get_object_or_404(
            LearningPath.objects.get_paths_visible_to_user(self.request.user),
            key=learning_path_key_str,
        )

        try:
            grading_criteria = learning_path.grading_criteria
        except ObjectDoesNotExist:
            return Response(
                {"detail": "Grading criteria not found for this learning path."},
                status=status.HTTP_404_NOT_FOUND,
            )

        grade = grading_criteria.calculate_grade(request.user)

        data = {
            "learning_path_key": learning_path_key_str,
            "grade": grade,
            "required_grade": grading_criteria.required_grade,
        }

        serializer = LearningPathGradeSerializer(data=data)
        if serializer.is_valid():
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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


class AllObjectTagsView(APIView):
    """
    API view to get all object tags for all courses.
    Returns a mapping of object_id -> tags.

    GET /api/learning_paths/v1/all_object_tags/

    Response format:
    {
        "course-v1:Org+Course+Run": {
            "tags": [
                {
                    "value": "Python",
                    "taxonomy_id": 1,
                    "taxonomy_name": "Subjects"
                }
            ],
            "taxonomies": {
                "1": {"id": 1, "name": "Subjects"}
            }
        }
    }
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        """Fetch all object tags across all tagged objects."""
        try:
            # Import the tagging API from openedx_tagging
            from openedx_tagging.core.tagging.models import ObjectTag

            # Query all object tags
            object_tags = ObjectTag.objects.select_related(
                'tag__taxonomy'
            ).filter(
                tag__taxonomy__enabled=True
            ).all()

            # Build the response structure
            result = {}

            for obj_tag in object_tags:
                object_id = obj_tag.object_id
                taxonomy_id = obj_tag.tag.taxonomy_id
                taxonomy_name = obj_tag.tag.taxonomy.name

                # Initialize object entry if it doesn't exist
                if object_id not in result:
                    result[object_id] = {
                        'tags': [],
                        'taxonomies': {}
                    }

                # Add taxonomy info if not already added
                if str(taxonomy_id) not in result[object_id]['taxonomies']:
                    result[object_id]['taxonomies'][str(taxonomy_id)] = {
                        'id': taxonomy_id,
                        'name': taxonomy_name
                    }

                # Add tag
                result[object_id]['tags'].append({
                    'value': obj_tag.tag.value,
                    'taxonomy_id': taxonomy_id,
                    'taxonomy_name': taxonomy_name,
                })

            return Response(result)

        except ImportError:
            # If openedx_tagging is not installed, return empty
            return Response({})
        except Exception as e:
            # Return error for debugging
            return Response(
                {"error": str(e), "detail": "Failed to fetch object tags"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class GroupCourseAssignmentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing Group Course Assignments.

    Allows admins to:
    - List all group-course assignments
    - Create new assignments (assign groups to courses)
    - Update existing assignments
    - Delete assignments
    """

    permission_classes = [IsAdminUser]
    serializer_class = GroupCourseAssignmentSerializer
    queryset = GroupCourseAssignment.objects.all().select_related("group", "assigned_by")
    filterset_fields = ["group", "course_id", "is_active", "auto_enroll"]
    search_fields = ["group__name", "course_id"]
    ordering_fields = ["created", "modified", "group__name"]
    ordering = ["-created"]

    def perform_create(self, serializer):
        """Set the assigned_by field when creating a new assignment."""
        serializer.save(assigned_by=self.request.user)


class BulkEnrollGroupToCourseView(APIView):
    """
    Bulk enrollment API for enrolling group members into courses.

    This view allows admins to bulk enroll all members of specified groups
    into specified courses, similar to the LearningPath bulk enrollment.
    """

    permission_classes = [IsAdminUser]

    @staticmethod
    def _process_input_data(request: Request) -> tuple[list[int], list[str]]:
        """Extract and validate input data from request."""
        data = request.data
        group_ids_str = data.get("group_ids", "")
        course_ids_str = data.get("course_ids", "")

        # Parse comma-separated strings
        group_ids = []
        if group_ids_str:
            try:
                group_ids = [int(gid.strip()) for gid in group_ids_str.split(",") if gid.strip()]
            except ValueError:
                raise ParseError("Invalid group_ids format. Must be comma-separated integers.")

        course_ids = [cid.strip() for cid in course_ids_str.split(",") if cid.strip()]

        return group_ids, course_ids

    @staticmethod
    def _validate_courses(course_ids: list[str]) -> list[CourseKey]:
        """Validate course IDs and return valid CourseKey objects."""
        valid_course_keys = []
        for course_id in course_ids:
            try:
                course_key = CourseKey.from_string(course_id)
                valid_course_keys.append(course_key)
            except InvalidKeyError:
                logger.warning("BulkEnrollGroupToCourseView: Invalid course key: %s", course_id)

        return valid_course_keys

    def post(self, request: Request, *args, **kwargs) -> Response:
        """
        Bulk enroll group members into courses.

        Example payload::

            {
                "group_ids": "1,2,3",
                "course_ids": "course-v1:edX+DemoX+Demo_Course,course-v1:edX+CS101+2023",
                "enrollment_mode": "audit",
                "create_assignment": true,
                "auto_enroll": true,
                "reason": "Bulk enrollment for new cohort",
                "org": "organization_name",
                "role": "student"
            }

        `group_ids` (str): Comma-separated list of Django Group IDs.
        `course_ids` (str): Comma-separated list of course IDs.
        `enrollment_mode` (str, optional): Enrollment mode (default: "audit").
        `create_assignment` (bool, optional): Create GroupCourseAssignment records (default: false).
        `auto_enroll` (bool, optional): Enable auto-enrollment for new group members (default: true).
        `reason` (str, optional): Reason for enrollment, used for audit.
        `org` (str, optional): Organization identifier, used for audit.
        `role` (str, optional): User role, used for audit.

        Returns enrollment statistics and audit records.
        """
        from django.contrib.auth.models import Group

        group_ids, course_ids_str = self._process_input_data(request)
        course_keys = self._validate_courses(course_ids_str)

        if not group_ids or not course_keys:
            raise ParseError("Both group_ids and course_ids are required.")

        # Get groups
        groups = Group.objects.filter(id__in=group_ids).prefetch_related("user_set")

        # Get enrollment parameters
        enrollment_mode = request.data.get("enrollment_mode", "audit")
        create_assignment = request.data.get("create_assignment", False)
        auto_enroll = request.data.get("auto_enroll", True)
        reason = request.data.get("reason", "")
        org = request.data.get("org", "")
        role = request.data.get("role", "")

        enrollments_created = 0
        enrollments_failed = 0
        assignments_created = 0
        audit_records = []

        for group in groups:
            for course_key in course_keys:
                # Optionally create GroupCourseAssignment
                assignment = None
                if create_assignment:
                    assignment, created = GroupCourseAssignment.objects.get_or_create(
                        group=group,
                        course_id=course_key,
                        defaults={
                            "enrollment_mode": enrollment_mode,
                            "auto_enroll": auto_enroll,
                            "assigned_by": request.user,
                            "reason": reason,
                        },
                    )
                    if created:
                        assignments_created += 1

                # Enroll all group members
                for user in group.user_set.all():
                    try:
                        # Use the compat function to enroll the user
                        success = enroll_user_in_course(user, course_key, mode=enrollment_mode)

                        # Create audit record
                        audit_record = GroupCourseEnrollmentAudit.objects.create(
                            assignment=assignment if assignment else None,
                            user=user,
                            enrolled_by=request.user,
                            status=GroupCourseEnrollmentAudit.SUCCESS if success else GroupCourseEnrollmentAudit.FAILED,
                            error_message="" if success else "Enrollment failed",
                            reason=reason,
                            org=org,
                            role=role,
                        )
                        audit_records.append(audit_record)

                        if success:
                            enrollments_created += 1
                        else:
                            enrollments_failed += 1

                    except Exception as e:  # pylint: disable=broad-except
                        logger.exception(
                            "BulkEnrollGroupToCourseView: Failed to enroll user %s in course %s",
                            user.username,
                            course_key,
                        )
                        enrollments_failed += 1

                        # Create failed audit record
                        GroupCourseEnrollmentAudit.objects.create(
                            assignment=assignment if assignment else None,
                            user=user,
                            enrolled_by=request.user,
                            status=GroupCourseEnrollmentAudit.FAILED,
                            error_message=str(e),
                            reason=reason,
                            org=org,
                            role=role,
                        )

        return Response(
            {
                "enrollments_created": enrollments_created,
                "enrollments_failed": enrollments_failed,
                "assignments_created": assignments_created,
                "audit_records_count": len(audit_records),
            },
            status=status.HTTP_201_CREATED,
        )


class SyncGroupEnrollmentsView(APIView):
    """
    API view to synchronize course enrollments based on current group membership.

    This view ensures that all current members of groups assigned to courses
    are enrolled, and optionally removes enrollments for ex-members.
    """

    permission_classes = [IsAdminUser]

    def post(self, request: Request, *args, **kwargs) -> Response:
        """
        Sync enrollments for group course assignments.

        Example payload::

            {
                "assignment_ids": "1,2,3",
                "remove_ex_members": false,
                "reason": "Monthly sync",
                "org": "organization_name"
            }

        `assignment_ids` (str, optional): Comma-separated list of GroupCourseAssignment IDs to sync.
            If not provided, syncs all active assignments with auto_enroll=True.
        `remove_ex_members` (bool, optional): Whether to unenroll users who are no longer in the group (default: false).
        `reason` (str, optional): Reason for sync operation.
        `org` (str, optional): Organization identifier.

        Returns statistics about the sync operation.
        """
        assignment_ids_str = request.data.get("assignment_ids", "")
        remove_ex_members = request.data.get("remove_ex_members", False)
        reason = request.data.get("reason", "Enrollment sync")
        org = request.data.get("org", "")

        # Get assignments to sync
        if assignment_ids_str:
            try:
                assignment_ids = [int(aid.strip()) for aid in assignment_ids_str.split(",") if aid.strip()]
                assignments = GroupCourseAssignment.objects.filter(id__in=assignment_ids, is_active=True)
            except ValueError:
                raise ParseError("Invalid assignment_ids format. Must be comma-separated integers.")
        else:
            # Default: sync all active assignments with auto_enroll enabled
            assignments = GroupCourseAssignment.objects.filter(is_active=True, auto_enroll=True)

        assignments = assignments.select_related("group").prefetch_related("group__user_set")

        enrollments_added = 0
        enrollments_removed = 0
        enrollments_skipped = 0

        for assignment in assignments:
            group_members = set(assignment.group.user_set.all())
            course_key = assignment.course_id

            # Enroll missing members
            for user in group_members:
                try:
                    success = enroll_user_in_course(user, course_key, mode=assignment.enrollment_mode)

                    if success:
                        enrollments_added += 1
                        GroupCourseEnrollmentAudit.objects.create(
                            assignment=assignment,
                            user=user,
                            enrolled_by=request.user,
                            status=GroupCourseEnrollmentAudit.SUCCESS,
                            reason=reason,
                            org=org,
                        )
                    else:
                        enrollments_skipped += 1
                        GroupCourseEnrollmentAudit.objects.create(
                            assignment=assignment,
                            user=user,
                            enrolled_by=request.user,
                            status=GroupCourseEnrollmentAudit.SKIPPED,
                            reason=f"{reason} - already enrolled",
                            org=org,
                        )

                except Exception as e:  # pylint: disable=broad-except
                    logger.exception(
                        "SyncGroupEnrollmentsView: Failed to enroll user %s in course %s",
                        user.username,
                        course_key,
                    )
                    GroupCourseEnrollmentAudit.objects.create(
                        assignment=assignment,
                        user=user,
                        enrolled_by=request.user,
                        status=GroupCourseEnrollmentAudit.FAILED,
                        error_message=str(e),
                        reason=reason,
                        org=org,
                    )

            # TODO: Implement remove_ex_members logic
            # This would require tracking which enrollments were created via group assignments
            # and unenrolling users who are no longer in the group

        return Response(
            {
                "assignments_synced": assignments.count(),
                "enrollments_added": enrollments_added,
                "enrollments_removed": enrollments_removed,
                "enrollments_skipped": enrollments_skipped,
            },
            status=status.HTTP_200_OK,
        )


class CoursePrerequisitesView(APIView):
    """
    API View to retrieve course prerequisites and check fulfillment status.

    This endpoint returns:
    - List of prerequisite courses
    - Whether prerequisites are fulfilled for the current user
    - Which prerequisites remain unfulfilled
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, course_key_str: str):
        """
        Get course prerequisites and fulfillment status for the current user.

        Returns:
            {
                "course_id": "course-v1:...",
                "has_prerequisites": true/false,
                "prerequisites": [
                    {
                        "course_id": "course-v1:...",
                        "display_name": "Org Course_Number"
                    }
                ],
                "all_prerequisites_met": true/false,
                "unfulfilled_prerequisites": [
                    {
                        "course_id": "course-v1:...",
                        "display_name": "Org Course_Number"
                    }
                ]
            }
        """
        try:
            course_key = CourseKey.from_string(course_key_str)
        except InvalidKeyError:
            raise ParseError("Invalid course key format.") from None

        # Try importing milestones helpers (may not be available in all Open edX installations)
        try:
            from common.djangoapps.util import milestones_helpers
            from xmodule.modulestore.django import modulestore
        except ImportError:
            # Milestones not available, return empty prerequisites
            logger.info(
                "CoursePrerequisitesView: Milestones helpers not available for course %s",
                course_key_str,
            )
            return Response(
                {
                    "course_id": course_key_str,
                    "has_prerequisites": False,
                    "prerequisites": [],
                    "all_prerequisites_met": True,
                    "unfulfilled_prerequisites": [],
                },
                status=status.HTTP_200_OK,
            )

        # Check if prerequisites are enabled
        if not milestones_helpers.is_prerequisite_courses_enabled():
            return Response(
                {
                    "course_id": course_key_str,
                    "has_prerequisites": False,
                    "prerequisites": [],
                    "all_prerequisites_met": True,
                    "unfulfilled_prerequisites": [],
                },
                status=status.HTTP_200_OK,
            )

        # Get course from modulestore
        try:
            course = modulestore().get_course(course_key)
            if not course:
                raise NotFound("Course not found.")
        except Exception as exc:
            raise NotFound("Course not found.") from exc

        # Get prerequisite courses for display
        prereq_courses = milestones_helpers.get_prerequisite_courses_display(course)

        # Get unfulfilled prerequisites for this user and course
        unfulfilled_dict = milestones_helpers.get_pre_requisite_courses_not_completed(
            request.user,
            [course_key],
        )

        # Extract unfulfilled prerequisites
        unfulfilled_prereqs = []
        if course_key in unfulfilled_dict:
            unfulfilled_prereqs = unfulfilled_dict[course_key].get("courses", [])

        # Format response
        prerequisites = [
            {
                "course_id": str(prereq["key"]),
                "display_name": prereq["display"],
            }
            for prereq in prereq_courses
        ]

        unfulfilled = [
            {
                "course_id": str(prereq["key"]),
                "display_name": prereq["display"],
            }
            for prereq in unfulfilled_prereqs
        ]

        return Response(
            {
                "course_id": course_key_str,
                "has_prerequisites": len(prerequisites) > 0,
                "prerequisites": prerequisites,
                "all_prerequisites_met": len(unfulfilled) == 0,
                "unfulfilled_prerequisites": unfulfilled,
            },
            status=status.HTTP_200_OK,
        )
