"""Django signal handler for learning paths plugin."""

# pylint: disable=unused-argument

import logging

from django.contrib.auth.models import Group
from django.db import IntegrityError
from django.db.models.signals import m2m_changed, post_save
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

    Args:
        sender: The intermediate model for the ManyToMany relation.
        instance: The Group instance.
        action: The type of update ("pre_add", "post_add", "pre_remove", "post_remove").
        pk_set: Set of primary keys of User instances being added/removed.
    """
    from learning_paths.compat import enroll_user_in_course

    # Only act on post_add (after users are added to the group)
    if action != "post_add":
        return

    # Get active course assignments for this group with auto_enroll enabled
    assignments = GroupCourseAssignment.objects.filter(
        group=instance,
        is_active=True,
        auto_enroll=True,
    )

    if not assignments.exists():
        logger.debug(
            "[GroupEnrollment] No active auto-enroll assignments for group %s. Skipping auto-enrollment.",
            instance.name,
        )
        return

    # Get the User model
    from django.contrib.auth import get_user_model

    User = get_user_model()
    users = User.objects.filter(pk__in=pk_set)

    logger.info(
        "[GroupEnrollment] Auto-enrolling %d users added to group %s into %d courses.",
        users.count(),
        instance.name,
        assignments.count(),
    )

    enrollments_created = 0
    enrollments_failed = 0

    for assignment in assignments:
        for user in users:
            try:
                success = enroll_user_in_course(user, assignment.course_id, mode=assignment.enrollment_mode)

                # Create audit record
                GroupCourseEnrollmentAudit.objects.create(
                    assignment=assignment,
                    user=user,
                    enrolled_by=user,  # Auto-enrollment, so user enrolls themselves
                    status=GroupCourseEnrollmentAudit.SUCCESS if success else GroupCourseEnrollmentAudit.SKIPPED,
                    reason=f"Auto-enrollment via group membership in {instance.name}",
                )

                if success:
                    enrollments_created += 1

            except Exception as e:  # pylint: disable=broad-except
                logger.exception(
                    "[GroupEnrollment] Failed to auto-enroll user %s in course %s",
                    user.username,
                    assignment.course_id,
                )
                enrollments_failed += 1

                GroupCourseEnrollmentAudit.objects.create(
                    assignment=assignment,
                    user=user,
                    enrolled_by=user,
                    status=GroupCourseEnrollmentAudit.FAILED,
                    error_message=str(e),
                    reason=f"Auto-enrollment via group membership in {instance.name}",
                )

    logger.info(
        "[GroupEnrollment] Auto-enrollment complete. Created: %d, Failed: %d",
        enrollments_created,
        enrollments_failed,
    )
