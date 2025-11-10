"""Django settings for the learning_paths app."""

from django.conf import Settings


def plugin_settings(settings: Settings):
    """
    Define plugin settings.

    See: https://docs.openedx.org/projects/edx-django-utils/en/latest/plugins/how_tos/how_to_create_a_plugin_app.html
    """
    # By default, un-enrolling from learning paths is only possible with staff
    # action. Learners cannot un-enroll themselves.
    # Set this True, if the learners should be allowed to un-enroll themselves.
    settings.LEARNING_PATHS_ALLOW_SELF_UNENROLLMENT = False

    # Milestone fulfillment execution mode
    # - 'async': Use Celery workers (recommended for production)
    # - 'sync': Execute inline in Django process (useful for development/testing)
    settings.LEARNING_PATHS_MILESTONE_MODE = getattr(
        settings,
        'LEARNING_PATHS_MILESTONE_MODE',
        'async'
    )

    settings.LEARNING_PATHS_MILESTONE_USE_ON_COMMIT = getattr(
        settings,
        'LEARNING_PATHS_MILESTONE_USE_ON_COMMIT',
        True  # Default: enabled for production safety
    )
