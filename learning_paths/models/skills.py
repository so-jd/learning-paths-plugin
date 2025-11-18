"""
Skills models for Learning Paths.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from .learning_paths import LearningPath


class Skill(TimeStampedModel):
    """
    A skill that can be associated with Learning Paths.

    .. no_pii:
    """

    display_name = models.CharField(max_length=255)

    def __str__(self):
        """User-friendly string representation of this model."""
        return self.display_name


class LearningPathSkill(TimeStampedModel):
    """
    Abstract base model for a skill required or acquired in a Learning Path..

    .. no_pii:
    """

    class Meta:
        """Model options."""

        abstract = True
        unique_together = ("learning_path", "skill")

    learning_path = models.ForeignKey(LearningPath, on_delete=models.CASCADE)
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE)
    level = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=_("The skill level associated with this course."),
    )

    def __str__(self):
        """User-friendly string representation of this model."""
        return "{}: {}".format(self.skill, self.level)


class RequiredSkill(LearningPathSkill):
    """
    A required skill for a Learning Path.

    .. no_pii:
    """


class AcquiredSkill(LearningPathSkill):
    """
    A skill acquired in a Learning Path.

    .. no_pii:
    """
