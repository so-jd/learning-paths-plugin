"""
Certificate/credential generation logic for learning paths.

This module handles:
- Checking if users are eligible for learning path certificates
- Generating certificates via the Credentials service API
"""

import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist

from learning_paths.api.v1.utils import get_aggregate_progress
from learning_paths.models import LearningPath

logger = logging.getLogger(__name__)

User = get_user_model()


def check_learning_path_completion_for_credential(user, learning_path):
    """
    Check if a user has completed a learning path and met grade requirements.

    This function evaluates whether a user is eligible for a learning path
    certificate by checking:
    1. Aggregate progress across all courses in the learning path
    2. Weighted grade across all courses in the learning path
    3. Both must meet the thresholds defined in LearningPathGradingCriteria

    Args:
        user: Django User instance
        learning_path: LearningPath instance

    Returns:
        tuple: (eligible: bool, data: dict) where data contains:
            - progress (float): Aggregate completion percentage (0.0-1.0)
            - grade (float): Weighted arithmetic mean grade (0.0-1.0)
            - required_completion (float): Required completion threshold
            - required_grade (float): Required grade threshold

    Example:
        >>> user = User.objects.get(username='learner123')
        >>> path = LearningPath.objects.get(key='path-v1:...')
        >>> eligible, data = check_learning_path_completion_for_credential(user, path)
        >>> if eligible:
        ...     print(f"User earned certificate with {data['grade']*100}% grade")
    """
    # Get aggregate progress
    progress = get_aggregate_progress(user, learning_path)

    # Get grading criteria and calculate grade
    try:
        grading_criteria = learning_path.grading_criteria
    except ObjectDoesNotExist:
        logger.warning(
            "[Credentials] No grading criteria found for learning path %s. "
            "Cannot check certificate eligibility.",
            learning_path.key,
        )
        return False, {
            'progress': progress,
            'grade': 0.0,
            'required_completion': 0.80,
            'required_grade': 0.75,
            'reason': 'no_grading_criteria',
        }

    grade = grading_criteria.calculate_grade(user)

    # Build response data
    data = {
        'progress': progress,
        'grade': grade,
        'required_completion': grading_criteria.required_completion,
        'required_grade': grading_criteria.required_grade,
    }

    # Check eligibility thresholds
    eligible = (
        progress >= grading_criteria.required_completion
        and grade >= grading_criteria.required_grade
    )

    if not eligible:
        # Determine specific reason for ineligibility
        if progress < grading_criteria.required_completion:
            data['reason'] = 'insufficient_completion'
        elif grade < grading_criteria.required_grade:
            data['reason'] = 'insufficient_grade'
        else:
            data['reason'] = 'unknown'

        logger.debug(
            "[Credentials] User %s not eligible for certificate in %s: %s "
            "(progress: %.2f/%.2f, grade: %.2f/%.2f)",
            user.username,
            learning_path.key,
            data['reason'],
            progress,
            grading_criteria.required_completion,
            grade,
            grading_criteria.required_grade,
        )
    else:
        data['reason'] = 'eligible'
        logger.info(
            "[Credentials] User %s is eligible for certificate in %s "
            "(progress: %.2f, grade: %.2f)",
            user.username,
            learning_path.key,
            progress,
            grade,
        )

    return eligible, data


def check_if_credential_already_exists(username, learning_path_uuid):
    """
    Check if a credential has already been issued for a user and learning path.

    Args:
        username (str): Username of the learner
        learning_path_uuid (UUID): UUID of the learning path

    Returns:
        bool: True if credential exists and is awarded, False otherwise
    """
    import requests
    from django.conf import settings

    credentials_api_url = getattr(settings, 'CREDENTIALS_SERVICE_URL', settings.LMS_ROOT_URL)
    credentials_api_url = f"{credentials_api_url}/api/v2/credentials/"

    try:
        # Fetch existing credentials for this user and program
        response = requests.get(
            credentials_api_url,
            params={
                'username': username,
                'program_uuid': str(learning_path_uuid),
                'status': 'awarded',
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        # Check if any credentials exist
        if data.get('results') and len(data['results']) > 0:
            logger.debug(
                "[Credentials] Credential already exists for user %s in learning path %s",
                username,
                learning_path_uuid,
            )
            return True

        return False

    except Exception as e:
        logger.warning(
            "[Credentials] Failed to check existing credentials for user %s: %s",
            username,
            str(e),
        )
        # If we can't check, assume it doesn't exist to avoid blocking
        return False
