"""
Compatibility layer for testing without Open edX.
"""

import logging
from datetime import datetime

from django.contrib.auth.models import AbstractBaseUser
from opaque_keys.edx.keys import CourseKey

log = logging.getLogger(__name__)


def get_user_course_grade(user: AbstractBaseUser, course_key: CourseKey):
    """
    Retrieve the CourseGrade object for a user in a specific course.
    """
    # pylint: disable=import-outside-toplevel, import-error
    from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory

    course_grade = CourseGradeFactory().read(user, course_key=course_key)
    return course_grade


def get_catalog_api_client(user: AbstractBaseUser):
    """
    Retrieve the api client for user.
    """
    # pylint: disable=import-outside-toplevel, import-error
    from openedx.core.djangoapps.catalog.utils import (
        get_catalog_api_client as api_client,
    )

    return api_client(user)


def get_course_keys_with_outlines() -> list[CourseKey]:
    """
    Retrieve course keys.
    """
    # pylint: disable=import-outside-toplevel, import-error
    from openedx.core.djangoapps.content.learning_sequences.api import (
        get_course_keys_with_outlines as course_keys_with_outlines,
    )

    return course_keys_with_outlines()


def get_course_dates(course_key: CourseKey) -> tuple[datetime | None, datetime | None]:
    """Retrieve course start and end dates."""
    # pylint: disable=import-outside-toplevel, import-error
    from openedx.core.djangoapps.content.course_overviews.models import CourseOverview

    try:
        overview = CourseOverview.objects.get(id=course_key)
        return overview.start, overview.end
    except CourseOverview.DoesNotExist:
        return None, None


def enroll_user_in_course(user: AbstractBaseUser, course_key: CourseKey, mode: str = "audit") -> bool:
    """
    Enroll a user in a course.

    Args:
        user: The user to enroll.
        course_key: The course to enroll the user in.
        mode: The enrollment mode (default: "audit"). Options: audit, verified, professional, etc.

    Returns:
        bool: True if enrollment succeeded or user is already enrolled, False otherwise.
    """
    # pylint: disable=import-outside-toplevel, import-error
    from common.djangoapps.student.api import CourseEnrollment
    from common.djangoapps.student.models.course_enrollment import (
        CourseEnrollmentException,
    )

    try:
        # Check if user is already enrolled
        existing_enrollment = CourseEnrollment.get_enrollment(user, course_key)
        if existing_enrollment and existing_enrollment.is_active:
            log.debug("User %s is already enrolled in course %s", user.username, course_key)
            return False  # Already enrolled, no new enrollment created

        # Enroll the user with the specified mode
        CourseEnrollment.enroll(user, course_key, mode=mode, check_access=True)
        log.info("Successfully enrolled user %s in course %s with mode %s", user.username, course_key, mode)
        return True
    except CourseEnrollmentException as exc:
        log.exception("Failed to enroll user %s in course %s: %s", user.username, course_key, exc)
        return False
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error enrolling user %s in course %s: %s", user.username, course_key, exc)
        return False


def unenroll_user_from_course(user: AbstractBaseUser, course_key: CourseKey) -> bool:
    """
    Unenroll a user from a course.

    Args:
        user: The user to unenroll.
        course_key: The course to unenroll the user from.

    Returns:
        bool: True if unenrollment succeeded, False otherwise.
    """
    # pylint: disable=import-outside-toplevel, import-error
    from common.djangoapps.student.api import CourseEnrollment
    from common.djangoapps.student.models.course_enrollment import (
        CourseEnrollmentException,
    )

    try:
        # Check if user is enrolled
        existing_enrollment = CourseEnrollment.get_enrollment(user, course_key)
        if not existing_enrollment or not existing_enrollment.is_active:
            log.debug("User %s is not enrolled in course %s", user.username, course_key)
            return False  # Not enrolled, nothing to do

        # Unenroll the user
        CourseEnrollment.unenroll(user, course_key)
        log.info("Successfully unenrolled user %s from course %s", user.username, course_key)
        return True
    except CourseEnrollmentException as exc:
        log.exception("Failed to unenroll user %s from course %s: %s", user.username, course_key, exc)
        return False
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error unenrolling user %s from course %s: %s", user.username, course_key, exc)
        return False
