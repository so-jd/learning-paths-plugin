"""
Admin for Enrollment management.
"""

import requests
from django.conf import settings
from django.contrib import admin, messages
from django_object_actions import DjangoObjectActions, action

from ..models import (
    LearningPathEnrollment,
    LearningPathEnrollmentAllowed,
    LearningPathEnrollmentAudit,
)


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
