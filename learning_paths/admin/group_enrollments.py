"""
Admin for Group-based enrollment management.
"""

from django import forms
from django.contrib import admin, auth, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpResponseRedirect
from django.urls import reverse
from django_object_actions import DjangoObjectActions, action

from ..models import GroupCourseAssignment, GroupCourseEnrollmentAudit

User = auth.get_user_model()


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
