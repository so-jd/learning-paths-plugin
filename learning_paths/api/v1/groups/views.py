"""
Views for group-based course enrollment.
"""

import logging

from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from rest_framework import status, viewsets
from rest_framework.exceptions import ParseError
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from learning_paths.compat import enroll_user_in_course
from learning_paths.models import GroupCourseAssignment, GroupCourseEnrollmentAudit

from .serializers import GroupCourseAssignmentSerializer

logger = logging.getLogger(__name__)


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
