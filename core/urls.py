"""
URLs for core (learning paths).
"""

from django.urls import include, path

urlpatterns = [
    path("api/learning_paths/", include("core.api.urls")),  # Keep URL for frontend compatibility
]
