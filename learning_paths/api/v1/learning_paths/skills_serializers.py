"""
Serializers for skills related to learning paths.
"""

from rest_framework import serializers

from learning_paths.models import AcquiredSkill, RequiredSkill, Skill


class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = ["id", "display_name"]


class RequiredSkillSerializer(serializers.ModelSerializer):
    """
    Serializer for required skill.
    """

    skill = SkillSerializer()

    class Meta:
        model = RequiredSkill
        fields = ["skill", "level"]


class AcquiredSkillSerializer(serializers.ModelSerializer):
    """
    Serializer for acquired skill.
    """

    skill = SkillSerializer()

    class Meta:
        model = AcquiredSkill
        fields = ["skill", "level"]
