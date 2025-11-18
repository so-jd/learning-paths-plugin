"""
Admin for Learning Path management.
"""

import os

from django import forms
from django.contrib import admin, auth, messages
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django_object_actions import DjangoObjectActions, action

from ..models import (
    AcquiredSkill,
    LearningPath,
    LearningPathEnrollment,
    LearningPathStep,
    RequiredSkill,
)
from .widgets import CourseKeyDatalistWidget, get_course_keys_with_outlines

User = auth.get_user_model()


class LearningPathStepForm(forms.ModelForm):
    """Form for Learning Path step."""

    def __init__(self, *args, **kwargs):
        """Lazily fetch course keys to avoid calling compat code in all environments."""
        super().__init__(*args, **kwargs)
        self._course_keys = get_course_keys_with_outlines()
        self.fields["course_key"].widget = CourseKeyDatalistWidget(choices=self._course_keys)

    course_key = forms.CharField(label=_("Course"))

    def clean_course_key(self):
        """Validate that the course key is on the list of available course keys."""
        course_key = self.cleaned_data.get("course_key")
        valid_keys = {str(key).strip() for key in self._course_keys}

        if course_key not in valid_keys:
            raise ValidationError(_("Invalid course key. Please select a course from the suggestions."))

        return course_key


class LearningPathStepInline(admin.TabularInline):
    """Inline Admin for Learning Path step."""

    model = LearningPathStep
    form = LearningPathStepForm
    fields = ("course_key",)


class AcquiredSkillInline(admin.TabularInline):
    """Inline Admin for Learning Path acquired skill."""

    model = AcquiredSkill


class RequiredSkillInline(admin.TabularInline):
    """Inline Admin for Learning Path required skill."""

    model = RequiredSkill


class BulkEnrollUsersForm(forms.ModelForm):
    """Form to bulk enroll users in a learning path."""

    usernames = forms.CharField(
        widget=forms.Textarea,
        help_text="Enter usernames separated by newlines",
        label="Bulk enroll users",
        required=False,
    )

    class Meta:
        """Form options."""

        model = LearningPath
        fields = "__all__"

    def clean_usernames(self):
        """Validate usernames and return a list of users."""
        data = self.cleaned_data["usernames"]
        if not data:
            return []
        usernames = [username.strip() for username in data.split("\n")]
        users = User.objects.filter(username__in=usernames)
        found_usernames = list(users.values_list("username", flat=True))
        invalid_usernames = set(usernames) - set(found_usernames)
        if invalid_usernames:
            raise ValidationError(f"The following usernames are not valid: {', '.join(invalid_usernames)}")
        return users


@admin.register(LearningPath)
class LearningPathAdmin(DjangoObjectActions, admin.ModelAdmin):
    """Admin for Learning Path."""

    model = LearningPath
    form = BulkEnrollUsersForm

    search_fields = [
        "display_name",
        "key",
    ]
    list_display = (
        "key",
        "display_name",
        "level",
        "duration",
        "invite_only",
    )
    list_filter = ("invite_only",)

    inlines = [
        LearningPathStepInline,
        RequiredSkillInline,
        AcquiredSkillInline,
    ]

    change_actions = ("duplicate_learning_path",)

    def save_related(self, request, form, formsets, change):
        """Save related objects and enroll users in the learning path."""
        super().save_related(request, form, formsets, change)
        with transaction.atomic():
            for user in form.cleaned_data["usernames"]:
                LearningPathEnrollment.objects.get_or_create(user=user, learning_path=form.instance)

    @action(label="Duplicate Learning Path", description="Create a copy of this Learning Path")
    def duplicate_learning_path(self, request, obj: LearningPath) -> HttpResponseRedirect:
        """Duplicate the learning path with a new unique key."""
        base_new_key = f"{str(obj.key)}_copy"
        new_key = base_new_key
        counter = 1

        while LearningPath.objects.filter(key=new_key).exists():
            new_key = f"{base_new_key}_{counter}"
            counter += 1

        with transaction.atomic():
            new_learning_path = LearningPath(
                key=new_key,
                display_name=f"{obj.display_name} (Copy)",
                subtitle=obj.subtitle,
                description=obj.description,
                level=obj.level,
                duration=obj.duration,
                time_commitment=obj.time_commitment,
                sequential=obj.sequential,
                invite_only=obj.invite_only,
            )

            if obj.image:
                with obj.image.open("rb") as original_file:
                    image_content = original_file.read()

                original_filename = os.path.basename(obj.image.name)
                new_learning_path.image.save(original_filename, ContentFile(image_content), save=False)

            new_learning_path.save()

            new_learning_path.refresh_from_db()
            new_learning_path.grading_criteria.required_completion = obj.grading_criteria.required_completion
            new_learning_path.grading_criteria.required_grade = obj.grading_criteria.required_grade
            new_learning_path.grading_criteria.save()

            for step in obj.steps.all():
                step.pk = None
                step.learning_path = new_learning_path
                step.save()

            for skill in obj.requiredskill_set.all():
                skill.pk = None
                skill.learning_path = new_learning_path
                skill.save()

            for skill in obj.acquiredskill_set.all():
                skill.pk = None
                skill.learning_path = new_learning_path
                skill.save()

        messages.success(request, f"Learning path duplicated successfully. New key: {new_key}")
        return HttpResponseRedirect(reverse("admin:learning_paths_learningpath_change", args=[new_learning_path.pk]))
