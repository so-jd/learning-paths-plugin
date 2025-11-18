"""
Admin for Skills management.
"""

from django.contrib import admin

from ..models import Skill


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    """Admin for Learning Path generic skill."""

    model = Skill
