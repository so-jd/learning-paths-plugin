"""
Celery tasks for learning paths plugin.
"""

import logging

from celery import shared_task
from opaque_keys.edx.keys import CourseKey

logger = logging.getLogger(__name__)

# Minimum completion percentage required for milestone fulfillment
MIN_COMPLETION_PERCENT = 95.0


def check_and_fulfill_course_milestone(user_id, course_key_str):
    """
    Check course completion and fulfill milestone if requirements are met.

    This function contains the core business logic for milestone fulfillment:
    1. Validates prerequisites are enabled
    2. Checks course completion percentage
    3. Checks if user has passing grade
    4. Fulfills milestone if both requirements met (≥95% completion AND passing grade)

    Args:
        user_id: The ID of the user who completed the course
        course_key_str: String representation of the course key

    Returns:
        dict: Result dictionary with keys:
            - success (bool): Whether milestone was fulfilled
            - reason (str): Reason for success/skip
            - completion_percent (float): Course completion percentage
            - grade_percent (float): Course grade percentage
            - has_passing_grade (bool): Whether user has passing grade

    Raises:
        Exception: If there's an error checking completion, grades, or fulfilling milestone
    """
    from django.contrib.auth import get_user_model
    from common.djangoapps.util import milestones_helpers
    from lms.djangoapps.courseware.courses import get_course_blocks_completion_summary
    from lms.djangoapps.grades.api import CourseGradeFactory
    from openedx.core.djangoapps.content.course_overviews.api import get_course_overview_or_none

    User = get_user_model()
    user = User.objects.get(id=user_id)
    course_key = CourseKey.from_string(course_key_str)

    # Check if prerequisites are enabled
    if not milestones_helpers.is_prerequisite_courses_enabled():
        return {
            'success': False,
            'reason': 'prerequisites_disabled',
            'completion_percent': 0,
            'grade_percent': 0,
            'has_passing_grade': False,
        }

    # Step 1: Check course completion
    completion_percent = 0
    summary = get_course_blocks_completion_summary(course_key, user)
    if summary:
        complete_count = summary.get("complete_count", 0)
        incomplete_count = summary.get("incomplete_count", 0)
        locked_count = summary.get("locked_count", 0)
        num_total_units = complete_count + incomplete_count + locked_count

        if num_total_units > 0:
            completion_percent = round(complete_count / num_total_units, 2) * 100

    # Step 2: Check if user has passing grade
    has_passing_grade = False
    grade_percent = 0
    course_overview = get_course_overview_or_none(course_key)
    if course_overview:
        course_grade = CourseGradeFactory().read(user, course_overview)
        if course_grade:
            grade_percent = course_grade.percent * 100
            has_passing_grade = course_grade.passed

    # Step 3: Evaluate eligibility (require ≥95% completion AND passing grade)
    if completion_percent < MIN_COMPLETION_PERCENT:
        return {
            'success': False,
            'reason': 'insufficient_completion',
            'completion_percent': completion_percent,
            'grade_percent': grade_percent,
            'has_passing_grade': has_passing_grade,
        }

    if not has_passing_grade:
        return {
            'success': False,
            'reason': 'not_passing',
            'completion_percent': completion_percent,
            'grade_percent': grade_percent,
            'has_passing_grade': has_passing_grade,
        }

    # Step 4: Fulfill the milestone
    milestones_helpers.fulfill_course_milestone(course_key, user)

    return {
        'success': True,
        'reason': 'milestone_fulfilled',
        'completion_percent': completion_percent,
        'grade_percent': grade_percent,
        'has_passing_grade': has_passing_grade,
    }


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 3, 'countdown': 60},
    retry_backoff=True,
)
def fulfill_course_milestone_task(self, user_id, course_key_str):
    """
    Celery task wrapper for milestone fulfillment.

    This task is triggered when a user completes a prerequisite course with
    a passing grade. It runs asynchronously to avoid blocking the web request.

    Args:
        user_id: The ID of the user who completed the course
        course_key_str: String representation of the course key

    Raises:
        Exception: If milestone fulfillment fails (will be retried)
    """
    try:
        result = check_and_fulfill_course_milestone(user_id, course_key_str)

        if result['success']:
            logger.info(
                "[Milestones Task] Fulfilled milestone for user_id=%s in course %s (completion: %.1f%%, grade: %.1f%%)",
                user_id,
                course_key_str,
                result['completion_percent'],
                result['grade_percent'],
            )
        else:
            logger.debug(
                "[Milestones Task] Skipped milestone for user_id=%s in course %s: %s (completion: %.1f%%, grade: %.1f%%)",
                user_id,
                course_key_str,
                result['reason'],
                result['completion_percent'],
                result['grade_percent'],
            )

    except Exception as e:
        logger.error(
            "[Milestones Task] Task failed for user_id=%s, course=%s: %s (attempt %s/%s)",
            user_id,
            course_key_str,
            str(e),
            self.request.retries + 1,
            self.max_retries,
        )
        raise
