"""
Group-based course enrollment models.
"""

from django.contrib import auth
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel
from opaque_keys.edx.django.models import CourseKeyField

User = auth.get_user_model()


class GroupCourseAssignment(TimeStampedModel):
    """
    Represents an assignment of a Django Auth Group to a course.

    This allows platform-wide groups to be assigned to courses, enabling
    bulk enrollment management and dynamic enrollment when users join groups.

    .. no_pii:
    """

    class Meta:
        """Model options."""

        unique_together = ("group", "course_id")
        verbose_name = _("Group Course Assignment")
        verbose_name_plural = _("Group Course Assignments")

    group = models.ForeignKey(
        "auth.Group",
        on_delete=models.CASCADE,
        related_name="course_assignments",
        help_text=_("The Django Auth Group to assign to the course."),
    )
    course_id = CourseKeyField(
        max_length=255,
        db_index=True,
        help_text=_("The course that the group is assigned to."),
    )
    enrollment_mode = models.CharField(
        max_length=50,
        default="audit",
        choices=[
            ("audit", _("Audit")),
            ("verified", _("Verified")),
            ("professional", _("Professional")),
            ("no-id-professional", _("No ID Professional")),
            ("credit", _("Credit")),
            ("honor", _("Honor")),
        ],
        help_text=_("The enrollment mode for group members."),
    )
    auto_enroll = models.BooleanField(
        default=True,
        help_text=_("Automatically enroll new group members in the course."),
    )
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="group_course_assignments",
        help_text=_("The user who created this assignment."),
    )
    reason = models.TextField(
        blank=True,
        help_text=_("Reason for this assignment (for audit purposes)."),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_("Whether this assignment is currently active."),
    )

    def __str__(self):
        """User-friendly string representation of this model."""
        return f"{self.group.name} → {self.course_id} ({self.enrollment_mode})"


class GroupCourseEnrollmentAudit(TimeStampedModel):
    """
    Audit model for tracking group-based course enrollments.

    Tracks individual enrollment operations that were performed as part
    of group course assignments.

    .. no_pii:
    """

    # State transition constants (similar to LearningPathEnrollmentAudit)
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"

    STATUS_CHOICES = (
        (SUCCESS, _("Success")),
        (FAILED, _("Failed")),
        (SKIPPED, _("Skipped")),
    )

    assignment = models.ForeignKey(
        GroupCourseAssignment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="enrollment_audits",
        help_text=_("The group course assignment that triggered this enrollment (null if assignment was deleted)."),
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text=_("The user who was enrolled (null if enrollment was for an email)."),
    )
    email = models.EmailField(
        blank=True,
        help_text=_("Email address for pre-registration enrollments."),
    )
    enrolled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="group_enrollments_performed",
        help_text=_("The admin/staff user who initiated the enrollment operation."),
    )
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default=SUCCESS,
        db_index=True,
        help_text=_("Status of the enrollment operation."),
    )
    error_message = models.TextField(
        blank=True,
        help_text=_("Error message if the enrollment failed."),
    )
    reason = models.TextField(
        blank=True,
        help_text=_("Reason for this enrollment operation."),
    )
    org = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text=_("Organization identifier for reporting."),
    )
    role = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Role of the enrollee."),
    )

    def __str__(self):
        """User-friendly string representation of this model."""
        enrollee = self.user.username if self.user else self.email
        return f"{enrollee} → {self.assignment.course_id} ({self.status})"

    class Meta:
        """Model options."""

        verbose_name = _("Group Course Enrollment Audit")
        verbose_name_plural = _("Group Course Enrollment Audits")
        indexes = [
            models.Index(fields=["created"]),
            models.Index(fields=["status", "created"]),
        ]
