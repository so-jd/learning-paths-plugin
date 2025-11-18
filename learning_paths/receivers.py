"""
Django signal handlers for learning paths plugin - Backward Compatibility Layer.

This module maintains backward compatibility by re-exporting all signal handlers
from the feature-based signal modules.
"""

# Import all signal modules to register their handlers
from .signals import enrollments, group_membership, milestones  # noqa: F401

# Re-export specific functions for backward compatibility
from .signals.enrollments import (
    create_enrollment_allowed_audit,
    create_enrollment_audit,
    process_pending_enrollments,
)
from .signals.group_membership import (
    auto_enroll_on_group_membership_change,
    auto_unenroll_on_assignment_deletion,
)
from .signals.milestones import (
    check_and_trigger_learning_path_credentials,
    connect_completion_signal,
    fulfill_milestone_on_block_completion,
    trigger_credential_check_after_milestone,
)

__all__ = [
    # Enrollment signals
    "process_pending_enrollments",
    "create_enrollment_audit",
    "create_enrollment_allowed_audit",
    # Group membership signals
    "auto_enroll_on_group_membership_change",
    "auto_unenroll_on_assignment_deletion",
    # Milestone signals
    "fulfill_milestone_on_block_completion",
    "connect_completion_signal",
    # Credential signals
    "check_and_trigger_learning_path_credentials",
    "trigger_credential_check_after_milestone",
]
