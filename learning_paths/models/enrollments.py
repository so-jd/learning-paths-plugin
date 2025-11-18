"""
Enrollment models for Learning Paths.
"""

from django.contrib import auth
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils import FieldTracker
from model_utils.models import TimeStampedModel

from .learning_paths import LearningPath

User = auth.get_user_model()


class LearningPathEnrollment(TimeStampedModel):
    """
    A user enrolled in a Learning Path.

    .. no_pii:
    """

    class Meta:
        """Model options."""

        unique_together = ("user", "learning_path")

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    learning_path = models.ForeignKey(LearningPath, on_delete=models.CASCADE)
    is_active = models.BooleanField(
        default=True,
        help_text=_("Indicates if the learner is enrolled or not in the Learning Path"),
    )
    tracker = FieldTracker(fields=["is_active"])

    def __str__(self):
        """User-friendly string representation of this model."""
        return "{}: {}".format(self.user, self.learning_path)


class LearningPathEnrollmentAllowed(TimeStampedModel):
    """
    Represents an allowed enrollment in a learning path for a user email.

    These objects can be created when learners are invited/enrolled by staff before
    they have registered and created an account, allowing future learners to enroll.

    .. pii: The email field is not retired to allow future learners to enroll.
    .. pii_types: email_address
    .. pii_retirement: retained
    """

    class Meta:
        """Model options."""

        unique_together = ("email", "learning_path")

    email = models.EmailField(db_index=True)
    learning_path = models.ForeignKey(LearningPath, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE, blank=True, null=True)
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_("Indicates if the enrollment allowance is active"),
    )

    def __str__(self):
        """User-friendly string representation of this model."""
        return f"LearningPathEnrollmentAllowed for {self.email} in {self.learning_path.key}"


class LearningPathEnrollmentAudit(TimeStampedModel):
    """
    Audit model for tracking changes to learning path enrollments.

    .. no_pii:
    """

    # State transition constants (copied from edx-platform to maintain consistency)
    UNENROLLED_TO_ALLOWEDTOENROLL = "from unenrolled to allowed to enroll"
    ALLOWEDTOENROLL_TO_ENROLLED = "from allowed to enroll to enrolled"
    ENROLLED_TO_ENROLLED = "from enrolled to enrolled"
    ENROLLED_TO_UNENROLLED = "from enrolled to unenrolled"
    UNENROLLED_TO_ENROLLED = "from unenrolled to enrolled"
    ALLOWEDTOENROLL_TO_UNENROLLED = "from allowed to enroll to unenrolled"
    UNENROLLED_TO_UNENROLLED = "from unenrolled to unenrolled"
    DEFAULT_TRANSITION_STATE = "N/A"

    TRANSITION_STATES = (
        (UNENROLLED_TO_ALLOWEDTOENROLL, UNENROLLED_TO_ALLOWEDTOENROLL),
        (ALLOWEDTOENROLL_TO_ENROLLED, ALLOWEDTOENROLL_TO_ENROLLED),
        (ENROLLED_TO_ENROLLED, ENROLLED_TO_ENROLLED),
        (ENROLLED_TO_UNENROLLED, ENROLLED_TO_UNENROLLED),
        (UNENROLLED_TO_ENROLLED, UNENROLLED_TO_ENROLLED),
        (ALLOWEDTOENROLL_TO_UNENROLLED, ALLOWEDTOENROLL_TO_UNENROLLED),
        (UNENROLLED_TO_UNENROLLED, UNENROLLED_TO_UNENROLLED),
        (DEFAULT_TRANSITION_STATE, DEFAULT_TRANSITION_STATE),
    )

    enrolled_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, related_name="learning_path_audit")
    enrollment = models.ForeignKey(
        LearningPathEnrollment,
        on_delete=models.CASCADE,
        null=True,
        related_name="audit",
    )
    enrollment_allowed = models.ForeignKey(
        LearningPathEnrollmentAllowed,
        on_delete=models.CASCADE,
        null=True,
        related_name="audit",
    )
    state_transition = models.CharField(max_length=255, choices=TRANSITION_STATES, default=DEFAULT_TRANSITION_STATE)
    reason = models.TextField(blank=True)
    org = models.CharField(max_length=255, blank=True, db_index=True)
    role = models.CharField(max_length=255, blank=True)

    def __str__(self):
        """User-friendly string representation of this model."""
        enrollee = "unknown"
        learning_path = "unknown"

        if self.enrollment:
            enrollee = self.enrollment.user
            learning_path = self.enrollment.learning_path.key
        elif self.enrollment_allowed:
            enrollee = self.enrollment_allowed.user or self.enrollment_allowed.email
            learning_path = self.enrollment_allowed.learning_path.key

        return f"{self.state_transition} for {enrollee} in {learning_path}"
