"""
Signal handlers for course completion milestones and learning path certificates.
"""

# pylint: disable=unused-argument

import logging

from django.db import transaction

logger = logging.getLogger(__name__)


# ============================================================================
# Course Completion Milestone Fulfillment
# ============================================================================


def _execute_milestone_check_sync(user_id, course_key_str):
    """
    Execute milestone check synchronously (called by on_commit callback).

    This function is executed AFTER the BlockCompletion transaction commits,
    ensuring data consistency and preventing race conditions.

    Args:
        user_id: The user ID who completed the block
        course_key_str: String representation of the course key
    """
    try:
        from django.contrib.auth import get_user_model
        from learning_paths.tasks import check_and_fulfill_course_milestone

        User = get_user_model()
        user = User.objects.get(id=user_id)

        result = check_and_fulfill_course_milestone(user_id, course_key_str)

        if result['success']:
            logger.info(
                "[Milestones] Fulfilled milestone for user %s in course %s "
                "(completion: %.1f%%, grade: %.1f%%) [sync+on_commit]",
                user.username,
                course_key_str,
                result['completion_percent'],
                result['grade_percent'],
            )
        else:
            logger.debug(
                "[Milestones] Skipped milestone for user %s in course %s: %s [sync+on_commit]",
                user.username, course_key_str, result['reason']
            )
    except Exception as e:
        logger.error(
            "[Milestones] Error in sync milestone check for course %s: %s",
            course_key_str, str(e)
        )


def _enqueue_milestone_task_async(user_id, course_key_str):
    """
    Enqueue milestone task asynchronously (called by on_commit callback).

    This function is executed AFTER the BlockCompletion transaction commits,
    ensuring that the Celery task is only enqueued if the transaction succeeds.

    No artificial countdown delay is needed since the transaction has already
    committed when this executes.

    Args:
        user_id: The user ID who completed the block
        course_key_str: String representation of the course key
    """
    try:
        from django.contrib.auth import get_user_model
        from learning_paths.tasks import fulfill_course_milestone_task

        User = get_user_model()
        user = User.objects.get(id=user_id)

        fulfill_course_milestone_task.apply_async(
            args=[user_id, course_key_str],
            # No countdown needed - transaction already committed!
        )
        logger.info(
            "[Milestones] Dispatched milestone task for user %s in course %s [async+on_commit]",
            user.username, course_key_str
        )
    except Exception as e:
        logger.error(
            "[Milestones] Error dispatching milestone task for course %s: %s",
            course_key_str, str(e)
        )


def fulfill_milestone_on_block_completion(sender, instance, created, **kwargs):
    """
    Signal handler that processes milestone fulfillment.

    This handler is triggered when a BlockCompletion is saved. It uses
    transaction.on_commit() to defer processing until AFTER the transaction
    commits, ensuring data consistency and preventing race conditions.

    Behavior based on LEARNING_PATHS_MILESTONE_MODE setting:
    - 'async' (DEFAULT): Enqueues Celery task after transaction commits
    - 'sync': Executes milestone check after transaction commits

    The transaction.on_commit() approach provides:
    - No race conditions (task runs after commit)
    - Rollback safety (task not enqueued if transaction rolls back)
    - Faster transactions (no I/O during transaction)
    - Better performance (no artificial countdown delay needed)

    See docs/ASYNC_APPROACHES_COMPARISON.md for detailed explanation.

    Args:
        sender: The BlockCompletion model class
        instance: The BlockCompletion instance being saved
        created: Boolean indicating if this is a new completion
        **kwargs: Additional signal parameters
    """
    logger.debug(
        "[Milestones] Signal fired for block %s, completion=%.2f",
        instance.block_key,
        instance.completion
    )

    # Only process when completion reaches 1.0 (fully complete)
    if instance.completion < 1.0:
        return

    user = instance.user
    block_key = instance.block_key
    course_key = block_key.course_key

    logger.info(
        "[Milestones] Processing completion for user %s in course %s",
        user.username,
        course_key
    )

    # Check if milestones are available and enabled
    try:
        from common.djangoapps.util import milestones_helpers
    except ImportError:
        logger.warning("[Milestones] Milestones framework not available")
        return

    prereqs_enabled = milestones_helpers.is_prerequisite_courses_enabled()
    logger.debug("[Milestones] Prerequisites enabled: %s", prereqs_enabled)

    if not prereqs_enabled:
        return

    # Check execution mode and on_commit settings
    from django.conf import settings
    execution_mode = getattr(settings, 'LEARNING_PATHS_MILESTONE_MODE', 'async')
    use_on_commit = getattr(settings, 'LEARNING_PATHS_MILESTONE_USE_ON_COMMIT', True)

    logger.debug(
        "[Milestones] Execution mode: %s, use_on_commit: %s for user %s in course %s",
        execution_mode,
        use_on_commit,
        user.username,
        course_key
    )

    # Prepare arguments for deferred execution
    user_id = user.id
    course_key_str = str(course_key)

    if execution_mode == 'sync':
        # SYNC MODE: Execute milestone check inline
        if use_on_commit:
            # PRODUCTION-SAFE: Execute after transaction commits
            # This prevents long-running operations (grade calculation) from
            # blocking the BlockCompletion transaction
            transaction.on_commit(
                lambda: _execute_milestone_check_sync(user_id, course_key_str)
            )
            # Also check for learning path certificate eligibility
            transaction.on_commit(
                lambda: trigger_credential_check_after_milestone(user_id, course_key_str)
            )
            logger.debug(
                "[Milestones] Registered on_commit callback for sync milestone check "
                "(user: %s, course: %s)",
                user.username, course_key
            )
        else:
            # LEGACY MODE: Execute immediately (NOT RECOMMENDED)
            # This runs expensive operations (grade calculation) INSIDE the transaction
            # Can cause performance issues and deadlocks under load
            logger.warning(
                "[Milestones] Using legacy sync mode without on_commit "
                "(not recommended for production)"
            )
            try:
                from learning_paths.tasks import check_and_fulfill_course_milestone

                result = check_and_fulfill_course_milestone(user_id, course_key_str)

                if result['success']:
                    logger.info(
                        "[Milestones] Fulfilled milestone for user %s in course %s "
                        "(completion: %.1f%%, grade: %.1f%%) [sync-legacy]",
                        user.username,
                        course_key,
                        result['completion_percent'],
                        result['grade_percent'],
                    )
                    # Also check for learning path credentials
                    check_and_trigger_learning_path_credentials(user_id, course_key_str)
                else:
                    logger.debug(
                        "[Milestones] Skipped milestone for user %s in course %s: %s [sync-legacy]",
                        user.username, course_key, result['reason']
                    )
            except Exception as e:
                logger.error(
                    "[Milestones] Error in legacy sync milestone check for user %s in course %s: %s",
                    user.username, course_key, str(e)
                )
    else:
        # ASYNC MODE (DEFAULT): Enqueue Celery task
        if use_on_commit:
            # PRODUCTION-SAFE: Enqueue task after transaction commits
            # Benefits:
            # - No race conditions (transaction already committed)
            # - Rollback safety (task not enqueued if rollback)
            # - Faster execution (no artificial countdown delay)
            # - Cleaner transactions (no message broker I/O during transaction)
            transaction.on_commit(
                lambda: _enqueue_milestone_task_async(user_id, course_key_str)
            )
            # Also check for learning path certificate eligibility
            transaction.on_commit(
                lambda: trigger_credential_check_after_milestone(user_id, course_key_str)
            )
            logger.debug(
                "[Milestones] Registered on_commit callback for async milestone task "
                "(user: %s, course: %s)",
                user.username, course_key
            )
        else:
            # LEGACY MODE: Enqueue immediately with countdown delay
            # Uses countdown=5 to mitigate race conditions, but this means:
            # - 5-second artificial delay before task executes
            # - Small race condition risk if transaction takes >5 seconds
            # - Task enqueued even if transaction rolls back
            logger.warning(
                "[Milestones] Using legacy async mode with countdown "
                "(consider enabling LEARNING_PATHS_MILESTONE_USE_ON_COMMIT)"
            )
            try:
                from learning_paths.tasks import fulfill_course_milestone_task

                fulfill_course_milestone_task.apply_async(
                    args=[user_id, course_key_str],
                    countdown=5,  # Artificial delay to allow transaction to commit
                )
                logger.info(
                    "[Milestones] Dispatched milestone task for user %s in course %s [async-legacy]",
                    user.username, course_key
                )
                # Also check for learning path credentials
                # In legacy mode, we call this directly since transaction.on_commit is not available
                check_and_trigger_learning_path_credentials(user_id, course_key_str)
            except Exception as e:
                logger.error(
                    "[Milestones] Error dispatching milestone task for user %s in course %s: %s",
                    user.username, course_key, str(e)
                )


# ============================================================================
# Manual Signal Connection
# ============================================================================


def connect_completion_signal():
    """
    Connect the block completion signal handler.

    Manually connects to the BlockCompletion post_save signal to fulfill
    course milestones when users complete course content. The handler will
    evaluate if the entire course is complete and if the user has a passing
    grade before fulfilling the milestone.
    """
    try:
        from completion.models import BlockCompletion
        from django.db.models.signals import post_save

        post_save.connect(
            fulfill_milestone_on_block_completion,
            sender=BlockCompletion,
            dispatch_uid='learning_paths_fulfill_milestone_on_block_completion',
        )
        logger.info("[Milestones] Connected BlockCompletion signal handler")
    except ImportError:
        logger.warning("[Milestones] BlockCompletion model not available")
    except Exception as e:
        logger.error("[Milestones] Error connecting BlockCompletion signal: %s", str(e))


# Auto-connect the signal when this module is imported
connect_completion_signal()


# ============================================================================
# Learning Path Certificate Generation
# ============================================================================


def check_and_trigger_learning_path_credentials(user_id, course_key_str):
    """
    Check if completing this course triggers any learning path certificate eligibility.

    This function is called after a course is completed. It finds all learning paths
    that contain this course and checks if the user has now completed the learning path
    and met the grade requirements. If so, it triggers certificate generation.

    Args:
        user_id (int): The user ID who completed the course
        course_key_str (str): String representation of the course key
    """
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from opaque_keys.edx.keys import CourseKey
    from learning_paths.models import LearningPath, LearningPathStep, LearningPathEnrollment
    from learning_paths.credentials import check_learning_path_completion_for_credential

    # Check if learning path credentials feature is enabled
    if not getattr(settings, 'LEARNING_PATHS_ENABLE_CREDENTIALS', False):
        logger.debug("[Credentials] Learning path credentials feature is disabled")
        return

    try:
        User = get_user_model()
        user = User.objects.get(id=user_id)
        course_key = CourseKey.from_string(course_key_str)

        # Find all learning paths that contain this course
        learning_path_steps = LearningPathStep.objects.filter(course_key=course_key).select_related('learning_path')

        if not learning_path_steps.exists():
            logger.debug(
                "[Credentials] Course %s is not part of any learning path. Skipping certificate check.",
                course_key_str,
            )
            return

        logger.info(
            "[Credentials] Checking certificate eligibility for user %s after completing course %s "
            "(found %d learning paths containing this course)",
            user.username,
            course_key_str,
            learning_path_steps.count(),
        )

        # Check each learning path for completion
        for step in learning_path_steps:
            learning_path = step.learning_path

            # Check if user is enrolled in this learning path
            try:
                enrollment = LearningPathEnrollment.objects.get(
                    user=user,
                    learning_path=learning_path,
                    is_active=True,
                )
            except LearningPathEnrollment.DoesNotExist:
                logger.debug(
                    "[Credentials] User %s is not enrolled in learning path %s. Skipping.",
                    user.username,
                    learning_path.key,
                )
                continue

            # Check if user is eligible for certificate
            eligible, data = check_learning_path_completion_for_credential(user, learning_path)

            if eligible:
                logger.info(
                    "[Credentials] User %s is eligible for certificate in learning path %s. "
                    "Queueing certificate generation task.",
                    user.username,
                    learning_path.key,
                )

                # Queue the certificate generation task
                from learning_paths.tasks import generate_learning_path_credential

                generate_learning_path_credential.delay(
                    user_id=user.id,
                    learning_path_key_str=str(learning_path.key),
                    completion_data=data,
                )
            else:
                logger.debug(
                    "[Credentials] User %s not yet eligible for certificate in learning path %s: %s "
                    "(progress: %.2f/%.2f, grade: %.2f/%.2f)",
                    user.username,
                    learning_path.key,
                    data.get('reason', 'unknown'),
                    data.get('progress', 0),
                    data.get('required_completion', 0),
                    data.get('grade', 0),
                    data.get('required_grade', 0),
                )

    except Exception as e:
        logger.error(
            "[Credentials] Error checking learning path credentials for user %s, course %s: %s",
            user_id,
            course_key_str,
            str(e),
        )


def trigger_credential_check_after_milestone(user_id, course_key_str):
    """
    Callback to check learning path credentials after milestone fulfillment.

    This function is designed to be called via transaction.on_commit() after
    a course milestone is fulfilled, ensuring that all data is committed before
    checking for learning path completion.

    Args:
        user_id (int): The user ID who completed the course
        course_key_str (str): String representation of the course key
    """
    try:
        check_and_trigger_learning_path_credentials(user_id, course_key_str)
    except Exception as e:
        logger.error(
            "[Credentials] Error in on_commit credential check for user %s, course %s: %s",
            user_id,
            course_key_str,
            str(e),
        )
