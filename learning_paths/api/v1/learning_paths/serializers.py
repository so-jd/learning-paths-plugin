"""
Serializers for Learning Path core management.
"""

import json

from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from rest_framework import serializers

from learning_paths.keys import LearningPathKey
from learning_paths.models import (
    AcquiredSkill,
    LearningPath,
    LearningPathGradingCriteria,
    LearningPathStep,
    RequiredSkill,
    Skill,
)

from .skills_serializers import AcquiredSkillSerializer, RequiredSkillSerializer

DEFAULT_STATUS = "active"
IMAGE_WIDTH = 1440
IMAGE_HEIGHT = 480


class LearningPathAsProgramSerializer(serializers.ModelSerializer):
    """
    Serialize LearningPath as a Program to be ingested by course-discovery.

    Mocked data example:
    https://github.com/openedx/course-discovery/blob/d6a57fd69479b3d5f5afb682d2668b58503a6af6/course_discovery/apps/course_metadata/data_loaders/tests/mock_data.py#L580
    """

    name = serializers.CharField(source="display_name")
    marketing_slug = serializers.SerializerMethodField()
    title = serializers.CharField(source="display_name")
    status = serializers.SerializerMethodField()
    banner_image_urls = serializers.SerializerMethodField()
    organizations = serializers.SerializerMethodField()
    course_codes = serializers.SerializerMethodField()

    def get_marketing_slug(self, obj):
        return str(obj.key)

    def get_status(self, obj):  # pylint: disable=unused-argument
        return DEFAULT_STATUS

    def get_banner_image_urls(self, obj):
        if obj.image:
            image_key = f"w{IMAGE_WIDTH}h{IMAGE_HEIGHT}"
            return {image_key: obj.image.url}
        return {}

    def get_organizations(self, obj):  # pylint: disable=unused-argument
        return []

    def get_course_codes(self, obj):
        """returns course_codes as expected by course-discovery"""
        course_codes_dict = {}
        learning_path_course_keys = [course.course_key for course in obj.steps.all()]
        for course_key in learning_path_course_keys:
            run_mode = {"course_key": str(course_key), "run_key": course_key.run}
            if course_key.course in course_codes_dict:
                course_codes_dict[course_key.course]["run_modes"].append(run_mode)
            else:
                course_codes_dict[course_key.course] = {"run_modes": [run_mode]}

        return [{"key": key, **value} for key, value in course_codes_dict.items()]

    class Meta:
        model = LearningPath
        fields = (
            "uuid",
            "name",
            "marketing_slug",
            "title",
            "subtitle",
            "status",
            "banner_image_urls",
            "organizations",
            "course_codes",
        )


class LearningPathStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningPathStep
        fields = ["order", "course_key", "course_dates", "weight"]


class LearningPathListSerializer(serializers.ModelSerializer):
    """Serializer for the learning path list."""

    steps = LearningPathStepSerializer(many=True, read_only=True)
    required_completion = serializers.FloatField(source="grading_criteria.required_completion", read_only=True)
    enrollment_date = serializers.SerializerMethodField()
    invite_only = serializers.BooleanField()
    image = serializers.ImageField(read_only=True)

    class Meta:
        model = LearningPath
        fields = [
            "key",
            "display_name",
            "image",
            "sequential",
            "steps",
            "required_completion",
            "enrollment_date",
            "invite_only",
        ]

    def get_enrollment_date(self, obj):
        """
        Check if the current user is enrolled in this learning path.
        """
        if hasattr(obj, "enrollment_date"):
            return obj.enrollment_date
        return None


class LearningPathDetailSerializer(LearningPathListSerializer):
    """
    Serializer for learning path details.
    """

    required_skills = RequiredSkillSerializer(source="requiredskill_set", many=True, read_only=True)
    acquired_skills = AcquiredSkillSerializer(source="acquiredskill_set", many=True, read_only=True)

    class Meta(LearningPathListSerializer.Meta):
        fields = LearningPathListSerializer.Meta.fields + [
            "subtitle",
            "description",
            "level",
            "duration",
            "time_commitment",
            "required_skills",
            "acquired_skills",
        ]


class LearningPathWriteSerializer(serializers.ModelSerializer):
    """
    Serializer for creating and updating learning paths.
    Handles multipart form data with JSON fields for nested relationships.
    """

    # Allow organization, path_number, path_run, path_group for key construction
    organization = serializers.CharField(write_only=True, required=False)
    path_number = serializers.CharField(write_only=True, required=False)
    path_run = serializers.CharField(write_only=True, required=False)
    path_group = serializers.CharField(write_only=True, required=False)

    # JSON fields that come as strings in multipart form data
    steps = serializers.CharField(required=False, allow_blank=True)
    required_skills = serializers.CharField(required=False, allow_blank=True)
    acquired_skills = serializers.CharField(required=False, allow_blank=True)

    # Grading criteria fields
    required_completion = serializers.FloatField(required=False)
    required_grade = serializers.FloatField(required=False)

    class Meta:
        model = LearningPath
        fields = [
            "key",
            "organization",
            "path_number",
            "path_run",
            "path_group",
            "display_name",
            "subtitle",
            "description",
            "image",
            "level",
            "duration",
            "time_commitment",
            "sequential",
            "invite_only",
            "steps",
            "required_skills",
            "acquired_skills",
            "required_completion",
            "required_grade",
        ]
        extra_kwargs = {
            "key": {"required": False},
        }

    def validate_steps(self, value):
        """Parse and validate steps JSON."""
        if not value:
            return []
        try:
            steps = json.loads(value) if isinstance(value, str) else value
            if not isinstance(steps, list):
                raise serializers.ValidationError("Steps must be a list")
            return steps
        except json.JSONDecodeError:
            raise serializers.ValidationError("Invalid JSON format for steps")

    def validate_required_skills(self, value):
        """Parse and validate required_skills JSON."""
        if not value:
            return []
        try:
            skills = json.loads(value) if isinstance(value, str) else value
            if not isinstance(skills, list):
                raise serializers.ValidationError("Required skills must be a list")
            return skills
        except json.JSONDecodeError:
            raise serializers.ValidationError("Invalid JSON format for required_skills")

    def validate_acquired_skills(self, value):
        """Parse and validate acquired_skills JSON."""
        if not value:
            return []
        try:
            skills = json.loads(value) if isinstance(value, str) else value
            if not isinstance(skills, list):
                raise serializers.ValidationError("Acquired skills must be a list")
            return skills
        except json.JSONDecodeError:
            raise serializers.ValidationError("Invalid JSON format for acquired_skills")

    def validate(self, attrs):
        """Validate and construct the learning path key if needed."""
        # If key is not provided but key components are, construct the key
        if not attrs.get("key"):
            org = attrs.get("organization")
            number = attrs.get("path_number")
            run = attrs.get("path_run")
            group = attrs.get("path_group", "default")

            if org and number and run:
                key_str = f"path-v1:{org}+{number}+{run}+{group}"
                try:
                    attrs["key"] = LearningPathKey.from_string(key_str)
                except InvalidKeyError as exc:
                    raise serializers.ValidationError({"key": f"Invalid learning path key format: {exc}"})
            else:
                raise serializers.ValidationError(
                    "Either 'key' or 'organization', 'path_number', and 'path_run' must be provided"
                )

        return attrs

    def create(self, validated_data):
        """Create a learning path with nested relationships."""
        # Extract nested data
        steps_data = validated_data.pop("steps", [])
        required_skills_data = validated_data.pop("required_skills", [])
        acquired_skills_data = validated_data.pop("acquired_skills", [])
        required_completion = validated_data.pop("required_completion", 80)
        required_grade = validated_data.pop("required_grade", 75)

        # Remove key construction fields
        validated_data.pop("organization", None)
        validated_data.pop("path_number", None)
        validated_data.pop("path_run", None)
        validated_data.pop("path_group", None)

        # Create the learning path
        learning_path = LearningPath.objects.create(**validated_data)

        # Create or update grading criteria
        LearningPathGradingCriteria.objects.update_or_create(
            learning_path=learning_path,
            defaults={
                "required_completion": required_completion,
                "required_grade": required_grade,
            },
        )

        # Create steps
        self._create_steps(learning_path, steps_data)

        # Create skills
        self._create_skills(learning_path, required_skills_data, RequiredSkill)
        self._create_skills(learning_path, acquired_skills_data, AcquiredSkill)

        return learning_path

    def update(self, instance, validated_data):
        """Update a learning path with nested relationships."""
        # Extract nested data
        steps_data = validated_data.pop("steps", None)
        required_skills_data = validated_data.pop("required_skills", None)
        acquired_skills_data = validated_data.pop("acquired_skills", None)
        required_completion = validated_data.pop("required_completion", None)
        required_grade = validated_data.pop("required_grade", None)

        # Remove key construction fields
        validated_data.pop("organization", None)
        validated_data.pop("path_number", None)
        validated_data.pop("path_run", None)
        validated_data.pop("path_group", None)
        validated_data.pop("key", None)  # Don't allow key updates

        # Update basic fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Update grading criteria if provided
        if required_completion is not None or required_grade is not None:
            criteria, _ = LearningPathGradingCriteria.objects.get_or_create(learning_path=instance)
            if required_completion is not None:
                criteria.required_completion = required_completion
            if required_grade is not None:
                criteria.required_grade = required_grade
            criteria.save()

        # Update steps if provided
        if steps_data is not None:
            instance.steps.all().delete()
            self._create_steps(instance, steps_data)

        # Update skills if provided
        if required_skills_data is not None:
            instance.requiredskill_set.all().delete()
            self._create_skills(instance, required_skills_data, RequiredSkill)

        if acquired_skills_data is not None:
            instance.acquiredskill_set.all().delete()
            self._create_skills(instance, acquired_skills_data, AcquiredSkill)

        return instance

    def _create_steps(self, learning_path, steps_data):
        """Create learning path steps from validated data."""
        for step_data in steps_data:
            course_key_str = step_data.get("course_key")
            if not course_key_str:
                continue

            try:
                course_key = CourseKey.from_string(course_key_str)
            except InvalidKeyError:
                # Skip invalid course keys
                continue

            LearningPathStep.objects.create(
                learning_path=learning_path,
                course_key=course_key,
                order=step_data.get("order", 1),
                weight=step_data.get("weight", 1.0),
            )

    def _create_skills(self, learning_path, skills_data, skill_model):
        """Create skills (required or acquired) from validated data."""
        for skill_data in skills_data:
            skill_name = skill_data.get("skill") or skill_data.get("display_name")
            if not skill_name:
                continue

            # Get or create the skill
            skill, _ = Skill.objects.get_or_create(display_name=skill_name)

            # Create the relationship
            skill_model.objects.create(
                learning_path=learning_path,
                skill=skill,
                level=skill_data.get("level"),
            )
