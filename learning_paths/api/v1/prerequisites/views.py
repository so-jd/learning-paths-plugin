"""
Views for course prerequisites.
"""

import logging

from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from rest_framework import status
from rest_framework.exceptions import NotFound, ParseError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


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
