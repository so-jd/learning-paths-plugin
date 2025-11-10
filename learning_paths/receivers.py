"""Django signal handler for learning paths plugin."""

# pylint: disable=unused-argument

import logging

from django.contrib.auth.models import Group
from django.db import IntegrityError
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from learning_paths.models import (
    GroupCourseAssignment,
    GroupCourseEnrollmentAudit,
    LearningPathEnrollment,
    LearningPathEnrollmentAllowed,
    LearningPathEnrollmentAudit,
)

logger = logging.getLogger(__name__)


def process_pending_enrollments(sender, instance, created, **kwargs):
    """
    Process pending enrollments after a user instance has been created.

    Bulk enrollment API allows enrolling users with just the email. So learners who
    do not have an account yet would also be enrolled. This information is stored
    in the LearningPathEnrollmentAllowed model. This signal handler processes such
    instances and created the corresponding LearningPathEnrollment objects.

    Args:
        sender: User model class.
        instance: The actual instance being saved.
        created: A boolean indicating whether this is a creation and not an update.
    """
    if not created:
        logger.debug(
            "[LearningPaths] Skipping processing of pending enrollments for user %s.",
            instance,
        )
        return

    logger.info("[LearningPaths] Processing pending enrollments for user %s", instance)
    pending_enrollments = LearningPathEnrollmentAllowed.objects.filter(email=instance.email, is_active=True)
    enrollments_created = 0

    for entry in pending_enrollments:
        try:
            audit_data = {
                "enrolled_by": instance,
                "state_transition": LearningPathEnrollmentAudit.ALLOWEDTOENROLL_TO_ENROLLED,
            }
            if last_allowed_audit := entry.audit.order_by("-created").first():
                for field in ["reason", "org", "role"]:
                    audit_data[field] = getattr(last_allowed_audit, field, "")

            enrollment = LearningPathEnrollment(learning_path=entry.learning_path, user=instance)
            enrollment._audit = audit_data  # pylint: disable=protected-access
            enrollment.save()
            enrollments_created += 1

            # Link existing audits from the "allowed to enroll" entry to the new enrollment.
            entry.audit.update(enrollment=enrollment)

        except IntegrityError:  # pragma: no cover
            logger.info(
                "[LearningPaths] Enrollment already exists for user %s in the learning path %s",
                instance,
                entry.learning_path.key,
            )
        finally:
            entry.is_active = False
            entry.user = instance
            entry.save()

    logger.info(
        "[LearningPaths] Processed %d pending Learning Path enrollments for user %s.",
        enrollments_created,
        instance,
    )


def _create_enrollment_audit(instance: LearningPathEnrollment | LearningPathEnrollmentAllowed, audit_data: dict):
    """Create an audit record for the given instance with the provided audit data."""
    # If a previous audit exists, copy over missing fields
    previous_audit = instance.audit.order_by("-created").first()
    if previous_audit:
        for field in ["reason", "org", "role"]:
            if not audit_data.get(field):
                audit_data[field] = getattr(previous_audit, field)

    instance.audit.create(
        state_transition=audit_data.get("state_transition"),
        enrolled_by=audit_data.get("enrolled_by"),
        reason=audit_data.get("reason", ""),
        org=audit_data.get("org", ""),
        role=audit_data.get("role", ""),
    )


@receiver(post_save, sender=LearningPathEnrollment)
def create_enrollment_audit(sender, instance, created, **kwargs):
    """Create audit records when LearningPathEnrollment is saved."""
    audit_data = getattr(instance, "_audit", {})

    # Determine state transition if not provided
    if "state_transition" not in audit_data:
        if created:
            audit_data["state_transition"] = LearningPathEnrollmentAudit.UNENROLLED_TO_ENROLLED
        elif instance.is_active and not instance.tracker.previous("is_active"):
            audit_data["state_transition"] = LearningPathEnrollmentAudit.UNENROLLED_TO_ENROLLED
        elif not instance.is_active and instance.tracker.previous("is_active"):
            audit_data["state_transition"] = LearningPathEnrollmentAudit.ENROLLED_TO_UNENROLLED
        elif instance.is_active and instance.tracker.previous("is_active"):
            audit_data["state_transition"] = LearningPathEnrollmentAudit.ENROLLED_TO_ENROLLED
        elif not instance.is_active and not instance.tracker.previous("is_active"):
            audit_data["state_transition"] = LearningPathEnrollmentAudit.UNENROLLED_TO_UNENROLLED
        else:  # pragma: no cover
            # No relevant state change. This should not happen.
            audit_data["state_transition"] = LearningPathEnrollmentAudit.DEFAULT_TRANSITION_STATE

    _create_enrollment_audit(instance, audit_data)


@receiver(post_save, sender=LearningPathEnrollmentAllowed)
def create_enrollment_allowed_audit(sender, instance, created, **kwargs):
    """Create audit records when LearningPathEnrollmentAllowed is saved."""
    # The audit data can be missing in the following scenarios:
    # 1. The instance is created with `get_or_create`, so we want to provide this data later.
    # 2. The instance is updated when the user creates an account. In this case, the audit record is already created for
    #    the enrollment record, so we do not need to create it here.
    if not (audit_data := getattr(instance, "_audit", {})):
        return

    audit_data.setdefault("state_transition", LearningPathEnrollmentAudit.UNENROLLED_TO_ALLOWEDTOENROLL)

    audit_data["state_transition"] = audit_data.get(
        "state_transition", LearningPathEnrollmentAudit.UNENROLLED_TO_ALLOWEDTOENROLL
    )

    _create_enrollment_audit(instance, audit_data)


@receiver(m2m_changed, sender=Group.user_set.through)
def auto_enroll_on_group_membership_change(sender, instance, action, pk_set, **kwargs):
    """
    Auto-enroll users when they are added to a group that has course assignments.
    Auto-unenroll users when they are removed from a group.

    Args:
        sender: The intermediate model for the ManyToMany relation.
        instance: Either a Group instance (when adding users to group) or User instance (when adding groups to user).
        action: The type of update ("pre_add", "post_add", "pre_remove", "post_remove").
        pk_set: Set of primary keys being added/removed (User PKs or Group PKs depending on which side triggered).
    """
    from django.contrib.auth import get_user_model
    from learning_paths.compat import enroll_user_in_course, unenroll_user_from_course

    # Only act on post_add (enrollment) and post_remove (unenrollment)
    if action not in ("post_add", "post_remove"):
        return

    is_enrolling = action == "post_add"

    User = get_user_model()

    # Determine if instance is a Group or User
    # When adding users to a group: instance=Group, pk_set=User IDs
    # When adding groups to a user: instance=User, pk_set=Group IDs
    if isinstance(instance, Group):
        # Adding users to a group
        groups = [instance]
        users = User.objects.filter(pk__in=pk_set)
    elif isinstance(instance, User):
        # Adding groups to a user
        groups = Group.objects.filter(pk__in=pk_set)
        users = [instance]
    else:
        logger.warning(
            "[GroupEnrollment] Unexpected instance type in m2m_changed signal: %s",
            type(instance).__name__,
        )
        return

    # Get active course assignments for these groups
    # For enrollment: require auto_enroll=True
    # For unenrollment: process all active assignments
    if is_enrolling:
        assignments = GroupCourseAssignment.objects.filter(
            group__in=groups,
            is_active=True,
            auto_enroll=True,
        )
    else:
        assignments = GroupCourseAssignment.objects.filter(
            group__in=groups,
            is_active=True,
        )

    if not assignments.exists():
        logger.debug(
            "[GroupEnrollment] No active assignments for groups. Skipping auto-%s.",
            "enrollment" if is_enrolling else "unenrollment",
        )
        return

    logger.info(
        "[GroupEnrollment] Auto-%s %d users in %d courses via %d group(s).",
        "enrolling" if is_enrolling else "unenrolling",
        len(users) if isinstance(users, list) else users.count(),
        assignments.count(),
        len(groups),
    )

    operations_successful = 0
    operations_failed = 0

    for assignment in assignments:
        for user in users:
            try:
                if is_enrolling:
                    success = enroll_user_in_course(user, assignment.course_id, mode=assignment.enrollment_mode)
                    reason = f"Auto-enrollment via group membership in {assignment.group.name}"
                    operation = "enroll"
                else:
                    success = unenroll_user_from_course(user, assignment.course_id)
                    reason = f"Auto-unenrollment via group removal from {assignment.group.name}"
                    operation = "unenroll"

                # Create audit record
                GroupCourseEnrollmentAudit.objects.create(
                    assignment=assignment,
                    user=user,
                    enrolled_by=user,  # Auto-operation, so user is the actor
                    status=GroupCourseEnrollmentAudit.SUCCESS if success else GroupCourseEnrollmentAudit.SKIPPED,
                    reason=reason,
                )

                if success:
                    operations_successful += 1

            except Exception as e:  # pylint: disable=broad-except
                logger.exception(
                    "[GroupEnrollment] Failed to auto-%s user %s in course %s",
                    operation,
                    user.username,
                    assignment.course_id,
                )
                operations_failed += 1

                GroupCourseEnrollmentAudit.objects.create(
                    assignment=assignment,
                    user=user,
                    enrolled_by=user,
                    status=GroupCourseEnrollmentAudit.FAILED,
                    error_message=str(e),
                    reason=reason,
                )

    logger.info(
        "[GroupEnrollment] Auto-%s complete. Successful: %d, Failed: %d",
        "enrollment" if is_enrolling else "unenrollment",
        operations_successful,
        operations_failed,
    )


@receiver(post_delete, sender=GroupCourseAssignment)
def auto_unenroll_on_assignment_deletion(sender, instance, **kwargs):
    """
    Auto-unenroll all group members when a GroupCourseAssignment is deleted.

    Args:
        sender: The GroupCourseAssignment model.
        instance: The GroupCourseAssignment being deleted.
    """
    from learning_paths.compat import unenroll_user_from_course

    logger.info(
        "[GroupEnrollment] GroupCourseAssignment deleted: %s → %s. Unenrolling all group members.",
        instance.group.name,
        instance.course_id,
    )

    unenrollments_successful = 0
    unenrollments_failed = 0

    # Get all users in the group
    for user in instance.group.user_set.all():
        try:
            success = unenroll_user_from_course(user, instance.course_id)

            # Create audit record
            GroupCourseEnrollmentAudit.objects.create(
                assignment=None,  # Assignment is being deleted, so can't reference it
                user=user,
                enrolled_by=None,  # System-initiated
                status=GroupCourseEnrollmentAudit.SUCCESS if success else GroupCourseEnrollmentAudit.SKIPPED,
                reason=f"Auto-unenrollment due to deletion of group-course assignment: {instance.group.name} → {instance.course_id}",
            )

            if success:
                unenrollments_successful += 1

        except Exception as e:  # pylint: disable=broad-except
            logger.exception(
                "[GroupEnrollment] Failed to unenroll user %s from course %s during assignment deletion",
                user.username,
                instance.course_id,
            )
            unenrollments_failed += 1

            GroupCourseEnrollmentAudit.objects.create(
                assignment=None,
                user=user,
                enrolled_by=None,
                status=GroupCourseEnrollmentAudit.FAILED,
                error_message=str(e),
                reason=f"Auto-unenrollment due to deletion of group-course assignment: {instance.group.name} → {instance.course_id}",
            )

    logger.info(
        "[GroupEnrollment] Assignment deletion unenrollment complete. Successful: %d, Failed: %d",
        unenrollments_successful,
        unenrollments_failed,
    )


# ============================================================================
# Course Completion Milestone Fulfillment
# ============================================================================


def fulfill_milestone_on_block_completion(sender, instance, created, **kwargs):
    """
    Signal handler that processes milestone fulfillment.

    This handler is triggered when a BlockCompletion is saved. Depending on the
    LEARNING_PATHS_MILESTONE_MODE setting, it either:
    - 'async': Dispatches to a Celery task (production mode)
    - 'sync': Executes inline in the Django process (development/testing mode)

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

    # Check execution mode setting
    from django.conf import settings
    execution_mode = getattr(settings, 'LEARNING_PATHS_MILESTONE_MODE', 'async')

    logger.info(
        "[Milestones] Execution mode: %s for user %s in course %s",
        execution_mode,
        user.username,
        course_key
    )

    if execution_mode == 'sync':
        # Execute synchronously in Django process
        try:
            from learning_paths.tasks import check_and_fulfill_course_milestone

            result = check_and_fulfill_course_milestone(user.id, str(course_key))

            if result['success']:
                logger.info(
                    "[Milestones] Fulfilled milestone for user %s in course %s (completion: %.1f%%, grade: %.1f%%) [sync]",
                    user.username,
                    course_key,
                    result['completion_percent'],
                    result['grade_percent'],
                )
            else:
                logger.debug(
                    "[Milestones] Skipped milestone for user %s in course %s: %s [sync]",
                    user.username, course_key, result['reason']
                )
        except Exception as e:
            logger.error(
                "[Milestones] Error in sync milestone check for user %s in course %s: %s",
                user.username, course_key, str(e)
            )
    else:
        # Execute asynchronously via Celery worker (default)
        try:
            from learning_paths.tasks import fulfill_course_milestone_task

            fulfill_course_milestone_task.apply_async(
                args=[user.id, str(course_key)],
                countdown=5,  # Wait 5 seconds to allow completion data to propagate
            )
            logger.info(
                "[Milestones] Dispatched milestone task for user %s in course %s [async]",
                user.username, course_key
            )
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
