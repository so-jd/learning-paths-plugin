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

    # =========================================================================
    # Learning Path Credentials/Certificates Settings
    # =========================================================================

    # Enable/disable certificate generation for learning paths
    # When enabled, learners who complete a learning path and meet grade
    # requirements will automatically receive a certificate via the Credentials service
    settings.LEARNING_PATHS_ENABLE_CREDENTIALS = getattr(
        settings,
        'LEARNING_PATHS_ENABLE_CREDENTIALS',
        False  # Default: disabled (must be explicitly enabled)
    )

    # URL for the Credentials service API
    # Defaults to the LMS_ROOT_URL if not specified
    # Example: 'https://credentials.example.com' or 'https://lms.example.com'
    settings.CREDENTIALS_SERVICE_URL = getattr(
        settings,
        'CREDENTIALS_SERVICE_URL',
        getattr(settings, 'LMS_ROOT_URL', 'http://localhost:8000')
    )

    # Default completion threshold for learning path certificates
    # Users must complete at least this percentage of the learning path
    # to be eligible for a certificate (0.0 to 1.0)
    # Note: This is a default; individual learning paths can override via LearningPathGradingCriteria
    settings.LEARNING_PATHS_DEFAULT_REQUIRED_COMPLETION = getattr(
        settings,
        'LEARNING_PATHS_DEFAULT_REQUIRED_COMPLETION',
        0.80  # 80% completion required by default
    )

    # Default grade threshold for learning path certificates
    # Users must achieve at least this weighted average grade across all courses
    # to be eligible for a certificate (0.0 to 1.0)
    # Note: This is a default; individual learning paths can override via LearningPathGradingCriteria
    settings.LEARNING_PATHS_DEFAULT_REQUIRED_GRADE = getattr(
        settings,
        'LEARNING_PATHS_DEFAULT_REQUIRED_GRADE',
        0.75  # 75% grade required by default
    )

    # Enable/disable email notifications when learning path certificates are awarded
    # When enabled, learners receive a congratulatory email when they earn a certificate
    # (this is handled by the Credentials service's ProgramCertificateIssuer)
    settings.SEND_EMAIL_ON_PROGRAM_COMPLETION = getattr(
        settings,
        'SEND_EMAIL_ON_PROGRAM_COMPLETION',
        True  # Default: enabled
    )
