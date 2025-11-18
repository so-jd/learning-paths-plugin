"""
Serializers for group-based course enrollment.
"""

from rest_framework import serializers

from core.models import GroupCourseAssignment, GroupCourseEnrollmentAudit


class GroupCourseAssignmentSerializer(serializers.ModelSerializer):
    """
    Serializer for GroupCourseAssignment model.
    """

    group_name = serializers.CharField(source="group.name", read_only=True)
    group_id = serializers.IntegerField(source="group.id", read_only=True)
    assigned_by_username = serializers.CharField(source="assigned_by.username", read_only=True, allow_null=True)
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = GroupCourseAssignment
        fields = (
            "id",
            "group",
            "group_id",
            "group_name",
            "course_id",
            "enrollment_mode",
            "auto_enroll",
            "assigned_by",
            "assigned_by_username",
            "reason",
            "is_active",
            "created",
            "modified",
            "member_count",
        )
        read_only_fields = ("id", "created", "modified")

    def get_member_count(self, obj):
        """Get the number of users in the group."""
        return obj.group.user_set.count()


class GroupCourseEnrollmentAuditSerializer(serializers.ModelSerializer):
    """
    Serializer for GroupCourseEnrollmentAudit model.
    """

    assignment_id = serializers.IntegerField(source="assignment.id", read_only=True)
    course_id = serializers.CharField(source="assignment.course_id", read_only=True)
    group_name = serializers.CharField(source="assignment.group.name", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True, allow_null=True)
    enrolled_by_username = serializers.CharField(source="enrolled_by.username", read_only=True, allow_null=True)

    class Meta:
        model = GroupCourseEnrollmentAudit
        fields = (
            "id",
            "assignment",
            "assignment_id",
            "course_id",
            "group_name",
            "user",
            "user_username",
            "email",
            "enrolled_by",
            "enrolled_by_username",
            "status",
            "error_message",
            "reason",
            "org",
            "role",
            "created",
        )
        read_only_fields = ("id", "created")
