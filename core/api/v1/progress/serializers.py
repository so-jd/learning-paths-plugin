"""
Serializers for Learning Path progress and grading.
"""

from rest_framework import serializers


# pylint: disable=abstract-method
class LearningPathProgressSerializer(serializers.Serializer):
    learning_path_key = serializers.CharField()
    progress = serializers.FloatField()
    required_completion = serializers.FloatField()


class LearningPathGradeSerializer(serializers.Serializer):
    """
    Serializer for learning path grade.
    """

    learning_path_key = serializers.CharField()
    grade = serializers.FloatField()
    required_grade = serializers.FloatField()
