"""
Serializers for Learning Path enrollments.
"""

from rest_framework import serializers

from core.models import LearningPathEnrollment


class LearningPathEnrollmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningPathEnrollment
        fields = ("user", "learning_path", "is_active", "created")
