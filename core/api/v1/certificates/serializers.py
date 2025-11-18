"""
Serializers for Learning Path certificates.
"""

from rest_framework import serializers


class LearningPathCertificateStatusSerializer(serializers.Serializer):
    """
    Serializer for learning path certificate status.

    Returns information about certificate eligibility and award status
    for a specific learning path and user.
    """

    learning_path_key = serializers.CharField()
    learning_path_uuid = serializers.UUIDField()
    username = serializers.CharField()
    is_eligible = serializers.BooleanField()
    progress = serializers.FloatField()
    required_completion = serializers.FloatField()
    grade = serializers.FloatField()
    required_grade = serializers.FloatField()
    certificate_awarded = serializers.BooleanField()
    certificate_uuid = serializers.UUIDField(required=False, allow_null=True)
    certificate_url = serializers.URLField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_null=True)
