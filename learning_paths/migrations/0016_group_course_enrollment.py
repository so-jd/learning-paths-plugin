# Generated manually for group-based course enrollment feature

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
import opaque_keys.edx.django.models


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("learning_paths", "0015_make_skill_level_optional"),
    ]

    operations = [
        migrations.CreateModel(
            name="GroupCourseAssignment",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "course_id",
                    opaque_keys.edx.django.models.CourseKeyField(
                        db_index=True,
                        help_text="The course that the group is assigned to.",
                        max_length=255,
                    ),
                ),
                (
                    "enrollment_mode",
                    models.CharField(
                        choices=[
                            ("audit", "Audit"),
                            ("verified", "Verified"),
                            ("professional", "Professional"),
                            ("no-id-professional", "No ID Professional"),
                            ("credit", "Credit"),
                            ("honor", "Honor"),
                        ],
                        default="audit",
                        help_text="The enrollment mode for group members.",
                        max_length=50,
                    ),
                ),
                (
                    "auto_enroll",
                    models.BooleanField(
                        default=True,
                        help_text="Automatically enroll new group members in the course.",
                    ),
                ),
                (
                    "reason",
                    models.TextField(
                        blank=True,
                        help_text="Reason for this assignment (for audit purposes).",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        db_index=True,
                        default=True,
                        help_text="Whether this assignment is currently active.",
                    ),
                ),
                (
                    "assigned_by",
                    models.ForeignKey(
                        help_text="The user who created this assignment.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="group_course_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        help_text="The Django Auth Group to assign to the course.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="course_assignments",
                        to="auth.group",
                    ),
                ),
            ],
            options={
                "verbose_name": "Group Course Assignment",
                "verbose_name_plural": "Group Course Assignments",
            },
        ),
        migrations.CreateModel(
            name="GroupCourseEnrollmentAudit",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "email",
                    models.EmailField(
                        blank=True,
                        help_text="Email address for pre-registration enrollments.",
                        max_length=254,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("success", "Success"),
                            ("failed", "Failed"),
                            ("skipped", "Skipped"),
                        ],
                        db_index=True,
                        default="success",
                        help_text="Status of the enrollment operation.",
                        max_length=50,
                    ),
                ),
                (
                    "error_message",
                    models.TextField(
                        blank=True,
                        help_text="Error message if the enrollment failed.",
                    ),
                ),
                (
                    "reason",
                    models.TextField(
                        blank=True,
                        help_text="Reason for this enrollment operation.",
                    ),
                ),
                (
                    "org",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        help_text="Organization identifier for reporting.",
                        max_length=255,
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        blank=True,
                        help_text="Role of the enrollee.",
                        max_length=255,
                    ),
                ),
                (
                    "assignment",
                    models.ForeignKey(
                        help_text="The group course assignment that triggered this enrollment.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="enrollment_audits",
                        to="learning_paths.groupcourseassignment",
                    ),
                ),
                (
                    "enrolled_by",
                    models.ForeignKey(
                        help_text="The admin/staff user who initiated the enrollment operation.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="group_enrollments_performed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        help_text="The user who was enrolled (null if enrollment was for an email).",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Group Course Enrollment Audit",
                "verbose_name_plural": "Group Course Enrollment Audits",
            },
        ),
        migrations.AddConstraint(
            model_name="groupcourseassignment",
            constraint=models.UniqueConstraint(
                fields=("group", "course_id"),
                name="learning_paths_groupcourseassignment_unique_group_course",
            ),
        ),
        migrations.AddIndex(
            model_name="groupcourseenrollmentaudit",
            index=models.Index(
                fields=["created"],
                name="learning_pa_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="groupcourseenrollmentaudit",
            index=models.Index(
                fields=["status", "created"],
                name="learning_pa_status_created_idx",
            ),
        ),
    ]
