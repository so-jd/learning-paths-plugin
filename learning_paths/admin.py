"""
Django Admin for learning_paths.
"""

import os

from django import forms
from django.contrib import admin, auth, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import models, transaction
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django_object_actions import DjangoObjectActions, action

from .compat import get_course_keys_with_outlines
from .models import (
    AcquiredSkill,
    GroupCourseAssignment,
    GroupCourseEnrollmentAudit,
    LearningPath,
    LearningPathEnrollment,
    LearningPathEnrollmentAllowed,
    LearningPathEnrollmentAudit,
    LearningPathStep,
    RequiredSkill,
    Skill,
)

User = auth.get_user_model()


def get_course_keys_choices():
    """Get course keys in an adequate format for a choice field."""
    yield None, ""
    for key in get_course_keys_with_outlines():
        yield key, key


class CourseKeyDatalistWidget(forms.TextInput):
    """A widget that provides a datalist for course keys."""

    def __init__(self, choices=None, attrs=None):
        """Initialize the widget with a datalist and apply styles."""
        attrs = attrs or {}
        attrs.update(
            {
                "style": "width: 30em;",
                "class": "form-control datalist-input",
                "placeholder": _("Type to search courses..."),
            }
        )
        super().__init__(attrs)
        self.choices = choices or []

    def render(self, name, value, attrs=None, renderer=None):
        """Render the widget with a datalist."""
        final_attrs = attrs or {}
        data_list_id = f"datalist_{name}"
        final_attrs["list"] = data_list_id

        text_input_html = super().render(name, value, attrs, renderer)
        data_list_id = f"datalist_{name}"
        options = "\n".join(f'<option value="{choice}" />' for choice in self.choices)
        datalist_html = f'<datalist id="{data_list_id}">\n{options}\n</datalist>'
        return f"{text_input_html}\n{datalist_html}"


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


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    """Admin for Learning Path generic skill."""

    model = Skill


class EnrollmentAuditInline(admin.TabularInline):
    """Inline admin for LearningPathEnrollmentAudit records."""

    model = LearningPathEnrollmentAudit
    fk_name = "enrollment"
    extra = 0
    exclude = ["enrollment_allowed"]
    readonly_fields = [
        "state_transition",
        "enrolled_by",
        "reason",
        "org",
        "role",
        "created",
    ]

    def has_add_permission(self, request, obj=None):
        """Disable manual creation of audit records."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disable deletion of audit records."""
        return False


class EnrollmentAllowedAuditInline(admin.TabularInline):
    """Inline admin for LearningPathEnrollmentAudit records related to enrollment allowed."""

    model = LearningPathEnrollmentAudit
    fk_name = "enrollment_allowed"
    extra = 0
    exclude = ["enrollment"]
    readonly_fields = [
        "state_transition",
        "enrolled_by",
        "reason",
        "org",
        "role",
        "created",
    ]

    def has_add_permission(self, request, obj=None):
        """Disable manual creation of audit records."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disable deletion of audit records."""
        return False


@admin.register(LearningPathEnrollment)
class EnrolledUsersAdmin(DjangoObjectActions, admin.ModelAdmin):
    """Admin for Learning Path enrollment."""

    model = LearningPathEnrollment
    raw_id_fields = ("user",)
    autocomplete_fields = ["learning_path"]
    inlines = [EnrollmentAuditInline]

    list_display = [
        "id",
        "user",
        "learning_path",
        "is_active",
        "created",
    ]

    list_filter = [
        "learning_path__key",
        "created",
        "is_active",
    ]

    search_fields = [
        "id",
        "user__username",
        "learning_path__key",
        "learning_path__display_name",
    ]

    change_actions = ("award_certificate", "revoke_certificate")
    actions = ["award_certificates_to_selected", "revoke_certificates_from_selected"]

    @action(label="Award Certificate", description="Manually award a learning path certificate to this user")
    def award_certificate(self, request, obj: LearningPathEnrollment):
        """
        Manually award a learning path certificate to a specific user.

        This action triggers certificate generation for the enrollment,
        even if the user hasn't fully met completion/grade requirements.
        Useful for special cases or manual overrides.
        """
        from learning_paths.tasks import generate_learning_path_credential

        if not obj.is_active:
            messages.error(request, f"Cannot award certificate: {obj.user.username} is not actively enrolled in {obj.learning_path.key}")
            return

        try:
            # Trigger certificate generation task
            result = generate_learning_path_credential.delay(
                user_id=obj.user.id,
                learning_path_key_str=str(obj.learning_path.key),
                completion_data=None,  # Let the task calculate eligibility
            )

            messages.success(
                request,
                f"Certificate generation task queued for {obj.user.username} in {obj.learning_path.display_name}. "
                f"Task ID: {result.id}"
            )
        except Exception as e:
            messages.error(request, f"Failed to queue certificate generation: {str(e)}")

    @action(label="Revoke Certificate", description="Revoke the learning path certificate for this user")
    def revoke_certificate(self, request, obj: LearningPathEnrollment):
        """
        Revoke a learning path certificate for a specific user.

        This action calls the Credentials service API to revoke (not delete)
        the certificate, changing its status from 'awarded' to 'revoked'.
        """
        import requests
        from django.conf import settings

        try:
            # Fetch the credential for this user and learning path
            credentials_api_url = getattr(settings, 'CREDENTIALS_SERVICE_URL', settings.LMS_ROOT_URL)
            list_url = f"{credentials_api_url}/api/v2/credentials/"

            response = requests.get(
                list_url,
                params={
                    'username': obj.user.username,
                    'program_uuid': str(obj.learning_path.uuid),
                    'status': 'awarded',
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            if not data.get('results') or len(data['results']) == 0:
                messages.warning(
                    request,
                    f"No awarded certificate found for {obj.user.username} in {obj.learning_path.display_name}"
                )
                return

            credential = data['results'][0]
            credential_uuid = credential['uuid']

            # Revoke the credential
            revoke_url = f"{credentials_api_url}/api/v2/credentials/{credential_uuid}/"
            revoke_response = requests.patch(
                revoke_url,
                json={'status': 'revoked'},
                timeout=10,
            )
            revoke_response.raise_for_status()

            messages.success(
                request,
                f"Successfully revoked certificate for {obj.user.username} in {obj.learning_path.display_name}"
            )

        except requests.exceptions.HTTPError as e:
            messages.error(request, f"HTTP error revoking certificate: {str(e)}")
        except requests.exceptions.RequestException as e:
            messages.error(request, f"Network error revoking certificate: {str(e)}")
        except Exception as e:
            messages.error(request, f"Error revoking certificate: {str(e)}")

    def award_certificates_to_selected(self, request, queryset):
        """
        Bulk action to award certificates to multiple selected enrollments.

        This queues certificate generation tasks for all selected enrollments.
        """
        from learning_paths.tasks import generate_learning_path_credential

        queued_count = 0
        skipped_count = 0

        for enrollment in queryset:
            if not enrollment.is_active:
                skipped_count += 1
                continue

            try:
                generate_learning_path_credential.delay(
                    user_id=enrollment.user.id,
                    learning_path_key_str=str(enrollment.learning_path.key),
                    completion_data=None,
                )
                queued_count += 1
            except Exception:
                skipped_count += 1

        if queued_count > 0:
            messages.success(request, f"Queued certificate generation for {queued_count} enrollment(s)")
        if skipped_count > 0:
            messages.warning(request, f"Skipped {skipped_count} enrollment(s) (inactive or error)")

    award_certificates_to_selected.short_description = "Award certificates to selected enrollments"

    def revoke_certificates_from_selected(self, request, queryset):
        """
        Bulk action to revoke certificates from multiple selected enrollments.

        This revokes awarded certificates for all selected enrollments.
        """
        import requests
        from django.conf import settings

        revoked_count = 0
        not_found_count = 0
        error_count = 0

        credentials_api_url = getattr(settings, 'CREDENTIALS_SERVICE_URL', settings.LMS_ROOT_URL)

        for enrollment in queryset:
            try:
                # Fetch credential
                list_url = f"{credentials_api_url}/api/v2/credentials/"
                response = requests.get(
                    list_url,
                    params={
                        'username': enrollment.user.username,
                        'program_uuid': str(enrollment.learning_path.uuid),
                        'status': 'awarded',
                    },
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()

                if not data.get('results') or len(data['results']) == 0:
                    not_found_count += 1
                    continue

                credential_uuid = data['results'][0]['uuid']

                # Revoke credential
                revoke_url = f"{credentials_api_url}/api/v2/credentials/{credential_uuid}/"
                revoke_response = requests.patch(
                    revoke_url,
                    json={'status': 'revoked'},
                    timeout=10,
                )
                revoke_response.raise_for_status()
                revoked_count += 1

            except Exception:
                error_count += 1

        if revoked_count > 0:
            messages.success(request, f"Successfully revoked {revoked_count} certificate(s)")
        if not_found_count > 0:
            messages.info(request, f"{not_found_count} enrollment(s) had no awarded certificate to revoke")
        if error_count > 0:
            messages.error(request, f"Failed to revoke {error_count} certificate(s)")

    revoke_certificates_from_selected.short_description = "Revoke certificates from selected enrollments"


@admin.register(LearningPathEnrollmentAllowed)
class EnrollmentAllowedAdmin(admin.ModelAdmin):
    """Admin configuration for LearningPathEnrollmentAllowed model."""

    list_display = [
        "id",
        "email",
        "get_user",
        "learning_path",
        "created",
    ]

    list_filter = [
        "learning_path",
        "created",
    ]

    search_fields = [
        "email",
        "user__username",
        "user__email",
        "learning_path__key",
    ]

    readonly_fields = [
        "user",
        "created",
        "modified",
    ]

    inlines = [EnrollmentAllowedAuditInline]

    def get_user(self, obj):
        """Get the associated user, if any."""
        return obj.user.username if obj.user else "-"

    get_user.short_description = "User"


@admin.register(LearningPathEnrollmentAudit)
class EnrollmentAuditAdmin(admin.ModelAdmin):
    """Admin configuration for LearningPathEnrollmentAudit model."""

    list_display = [
        "id",
        "state_transition",
        "enrolled_by",
        "get_enrollee",
        "get_learning_path",
        "created",
        "org",
        "role",
    ]

    list_filter = [
        "state_transition",
        "created",
        "org",
        "role",
    ]

    search_fields = [
        "enrolled_by__username",
        "enrolled_by__email",
        "enrollment__user__username",
        "enrollment__user__email",
        "enrollment_allowed__email",
        "enrollment__learning_path__key",
        "enrollment_allowed__learning_path__key",
        "reason",
    ]

    readonly_fields = [
        "enrollment",
        "enrollment_allowed",
        "enrolled_by",
        "state_transition",
        "created",
        "modified",
    ]

    def get_enrollee(self, obj):
        """Get the enrollee (user or email)."""
        if obj.enrollment:
            return obj.enrollment.user.username
        elif obj.enrollment_allowed:
            return obj.enrollment_allowed.user.username if obj.enrollment_allowed.user else obj.enrollment_allowed.email
        return "-"

    get_enrollee.short_description = "Enrollee"

    def get_learning_path(self, obj):
        """Get the learning path title."""
        if obj.enrollment:
            return obj.enrollment.learning_path.key
        elif obj.enrollment_allowed:
            return obj.enrollment_allowed.learning_path.key
        return "-"

    get_learning_path.short_description = "Learning Path"


class GroupCourseEnrollmentAuditInline(admin.TabularInline):
    """Inline admin for GroupCourseEnrollmentAudit records."""

    model = GroupCourseEnrollmentAudit
    fk_name = "assignment"
    extra = 0
    readonly_fields = [
        "user",
        "email",
        "enrolled_by",
        "status",
        "error_message",
        "reason",
        "org",
        "role",
        "created",
    ]
    fields = ["user", "email", "status", "error_message", "enrolled_by", "created"]

    def has_add_permission(self, request, obj=None):
        """Disable manual creation of audit records."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disable deletion of audit records."""
        return False


@admin.register(GroupCourseAssignment)
class GroupCourseAssignmentAdmin(DjangoObjectActions, admin.ModelAdmin):
    """Admin for Group Course Assignment."""

    model = GroupCourseAssignment

    list_display = [
        "id",
        "group",
        "course_id",
        "enrollment_mode",
        "auto_enroll",
        "is_active",
        "get_member_count",
        "assigned_by",
        "created",
    ]

    list_filter = [
        "enrollment_mode",
        "auto_enroll",
        "is_active",
        "created",
    ]

    search_fields = [
        "group__name",
        "course_id",
        "assigned_by__username",
    ]

    readonly_fields = ["assigned_by", "created", "modified"]

    fields = [
        "group",
        "course_id",
        "enrollment_mode",
        "auto_enroll",
        "is_active",
        "reason",
        "assigned_by",
        "created",
        "modified",
    ]

    inlines = [GroupCourseEnrollmentAuditInline]

    change_actions = ("enroll_all_members",)

    def get_member_count(self, obj):
        """Get the number of users in the group."""
        return obj.group.user_set.count()

    get_member_count.short_description = "Group Members"

    def save_model(self, request, obj, form, change):
        """Set the assigned_by field when creating a new assignment."""
        if not change:  # Only set on creation
            obj.assigned_by = request.user
        super().save_model(request, obj, form, change)

    @action(label="Enroll All Members", description="Enroll all current group members in the assigned course")
    def enroll_all_members(self, request, obj: GroupCourseAssignment):
        """Bulk enroll all current group members in the assigned course."""
        from learning_paths.compat import enroll_user_in_course

        enrollments_created = 0
        enrollments_failed = 0

        for user in obj.group.user_set.all():
            try:
                success = enroll_user_in_course(user, obj.course_id, mode=obj.enrollment_mode)

                # Create audit record
                GroupCourseEnrollmentAudit.objects.create(
                    assignment=obj,
                    user=user,
                    enrolled_by=request.user,
                    status=GroupCourseEnrollmentAudit.SUCCESS if success else GroupCourseEnrollmentAudit.FAILED,
                    error_message="" if success else "Enrollment failed",
                    reason="Manual enrollment via admin action",
                )

                if success:
                    enrollments_created += 1
                else:
                    enrollments_failed += 1

            except Exception as e:  # pylint: disable=broad-except
                enrollments_failed += 1
                GroupCourseEnrollmentAudit.objects.create(
                    assignment=obj,
                    user=user,
                    enrolled_by=request.user,
                    status=GroupCourseEnrollmentAudit.FAILED,
                    error_message=str(e),
                    reason="Manual enrollment via admin action",
                )

        if enrollments_failed > 0:
            messages.warning(
                request,
                f"Enrolled {enrollments_created} members successfully. {enrollments_failed} enrollments failed.",
            )
        else:
            messages.success(request, f"Successfully enrolled {enrollments_created} group members.")


@admin.register(GroupCourseEnrollmentAudit)
class GroupCourseEnrollmentAuditAdmin(admin.ModelAdmin):
    """Admin configuration for GroupCourseEnrollmentAudit model."""

    list_display = [
        "id",
        "get_group_name",
        "get_course_id",
        "get_user_display",
        "status",
        "enrolled_by",
        "created",
    ]

    list_filter = [
        "status",
        "created",
        "assignment__group",
        "assignment__course_id",
    ]

    search_fields = [
        "user__username",
        "user__email",
        "email",
        "assignment__group__name",
        "assignment__course_id",
        "enrolled_by__username",
    ]

    readonly_fields = [
        "assignment",
        "user",
        "email",
        "enrolled_by",
        "status",
        "error_message",
        "reason",
        "org",
        "role",
        "created",
        "modified",
    ]

    def get_group_name(self, obj):
        """Get the group name from the assignment."""
        if obj.assignment:
            return obj.assignment.group.name
        # Try to extract from reason field if assignment was deleted
        if "group-course assignment:" in obj.reason:
            import re
            match = re.search(r'assignment: (.+?) →', obj.reason)
            return match.group(1) if match else "[Deleted Assignment]"
        return "[Deleted Assignment]"

    get_group_name.short_description = "Group"

    def get_course_id(self, obj):
        """Get the course ID from the assignment."""
        if obj.assignment:
            return str(obj.assignment.course_id)
        # Try to extract from reason field if assignment was deleted
        if "→" in obj.reason:
            import re
            match = re.search(r'→ (.+?)(?:\s|$)', obj.reason)
            return match.group(1) if match else "[Deleted Assignment]"
        return "[Deleted Assignment]"

    get_course_id.short_description = "Course"

    def get_user_display(self, obj):
        """Get the user or email for display."""
        if obj.user:
            return obj.user.username
        return obj.email or "-"

    get_user_display.short_description = "User/Email"

    def has_add_permission(self, request):
        """Disable manual creation of audit records."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disable deletion of audit records."""
        return False


class BulkAddUsersToGroupForm(forms.Form):
    """Form to bulk add users to a group by username or email."""

    users_input = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 10, "cols": 80}),
        help_text="Enter usernames or emails separated by newlines, commas, or spaces",
        label="Usernames or Emails",
        required=True,
    )

    def __init__(self, *args, **kwargs):
        self.group = kwargs.pop("group", None)
        super().__init__(*args, **kwargs)

    def clean_users_input(self):
        """Parse and validate usernames/emails."""
        import re

        data = self.cleaned_data["users_input"]
        if not data:
            return []

        # Split by newlines, commas, or multiple spaces
        identifiers = re.split(r"[\n,\s]+", data.strip())
        identifiers = [i.strip() for i in identifiers if i.strip()]

        if not identifiers:
            raise ValidationError("Please provide at least one username or email.")

        # Try to find users by username or email
        users = []
        not_found = []

        for identifier in identifiers:
            user = User.objects.filter(models.Q(username=identifier) | models.Q(email=identifier)).first()
            if user:
                users.append(user)
            else:
                not_found.append(identifier)

        if not_found:
            raise ValidationError(
                f"The following {len(not_found)} user(s) were not found: {', '.join(not_found[:10])}"
                + (f" and {len(not_found) - 10} more..." if len(not_found) > 10 else "")
            )

        return users


class GroupCourseAssignmentInline(admin.TabularInline):
    """Inline display of course assignments for a group."""

    model = GroupCourseAssignment
    fk_name = "group"  # Explicitly specify the foreign key field
    extra = 0
    fields = ["course_id", "enrollment_mode", "auto_enroll", "is_active", "assigned_by", "created"]
    readonly_fields = ["assigned_by", "created"]
    can_delete = True

    def has_add_permission(self, request, obj=None):
        """Allow adding assignments from the group admin."""
        return True


class EnhancedGroupAdmin(DjangoObjectActions, BaseGroupAdmin):
    """Enhanced Group Admin with bulk user management and course assignments."""

    change_actions = ("bulk_add_users", "view_course_assignments")

    # Declare inlines as a class attribute (the standard Django way)
    inlines = [GroupCourseAssignmentInline]

    @action(label="Bulk Add Users", description="Add multiple users to this group at once")
    def bulk_add_users(self, request, obj: Group):
        """Bulk add users to a group."""
        from django.shortcuts import render

        if request.method == "POST":
            form = BulkAddUsersToGroupForm(request.POST, group=obj)
            if form.is_valid():
                users = form.cleaned_data["users_input"]
                added_count = 0

                for user in users:
                    if not obj.user_set.filter(pk=user.pk).exists():
                        obj.user_set.add(user)
                        added_count += 1

                messages.success(
                    request,
                    f"Successfully added {added_count} user(s) to group '{obj.name}'. "
                    f"{len(users) - added_count} were already members.",
                )
                return HttpResponseRedirect(reverse("admin:auth_group_change", args=[obj.pk]))
        else:
            form = BulkAddUsersToGroupForm(group=obj)

        context = {
            "form": form,
            "group": obj,
            "opts": self.model._meta,
            "title": f"Bulk Add Users to {obj.name}",
        }
        return render(request, "admin/learning_paths/bulk_add_users.html", context)

    @action(label="View Course Assignments", description="View and manage course assignments for this group")
    def view_course_assignments(self, request, obj: Group):
        """Redirect to course assignments filtered by this group."""
        url = reverse("admin:learning_paths_groupcourseassignment_changelist")
        return HttpResponseRedirect(f"{url}?group__id__exact={obj.pk}")

    def get_member_count(self, obj):
        """Display the number of users in the group."""
        return obj.user_set.count()

    get_member_count.short_description = "Members"

    list_display = BaseGroupAdmin.list_display + ("get_member_count",)


# Unregister the default Group admin and register our enhanced version
admin.site.unregister(Group)
admin.site.register(Group, EnhancedGroupAdmin)
