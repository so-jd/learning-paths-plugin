"""Tests for milestone fulfillment tasks."""

import pytest
from unittest.mock import Mock, patch, MagicMock, PropertyMock
from opaque_keys.edx.keys import CourseKey

from learning_paths.tasks import check_and_fulfill_course_milestone, MIN_COMPLETION_PERCENT, fulfill_course_milestone_task
from learning_paths.receivers import fulfill_milestone_on_block_completion
from .factories import UserFactory


@pytest.fixture
def user():
    """Create a test user."""
    return UserFactory()


@pytest.fixture
def course_key_str():
    """Return a test course key string."""
    return "course-v1:edX+DemoX+Demo_Course"


@pytest.fixture
def course_key(course_key_str):
    """Return a CourseKey object."""
    return CourseKey.from_string(course_key_str)


@pytest.fixture
def mock_completion_summary():
    """Mock completion summary with 100% completion."""
    return {
        'complete_count': 10,
        'incomplete_count': 0,
        'locked_count': 0,
    }


@pytest.fixture
def mock_course_grade():
    """Mock a passing course grade."""
    grade = Mock()
    grade.percent = 0.85
    grade.passed = True
    return grade


@pytest.fixture
def mock_course_overview():
    """Mock course overview."""
    overview = Mock()
    overview.id = CourseKey.from_string("course-v1:edX+DemoX+Demo_Course")
    return overview


@pytest.mark.django_db
class TestCheckAndFulfillCourseMilestone:
    """Tests for check_and_fulfill_course_milestone function."""

    @patch('learning_paths.tasks.milestones_helpers')
    def test_prerequisites_disabled(self, mock_milestones, user, course_key_str):
        """
        GIVEN prerequisites feature is disabled
        WHEN check_and_fulfill_course_milestone is called
        THEN it returns success=False with reason 'prerequisites_disabled'
        AND milestone is not fulfilled
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = False

        result = check_and_fulfill_course_milestone(user.id, course_key_str)

        assert result['success'] is False
        assert result['reason'] == 'prerequisites_disabled'
        assert result['completion_percent'] == 0
        assert result['grade_percent'] == 0
        assert result['has_passing_grade'] is False
        mock_milestones.fulfill_course_milestone.assert_not_called()

    @patch('learning_paths.tasks.get_course_overview_or_none')
    @patch('learning_paths.tasks.CourseGradeFactory')
    @patch('learning_paths.tasks.get_course_blocks_completion_summary')
    @patch('learning_paths.tasks.milestones_helpers')
    def test_insufficient_completion(
        self,
        mock_milestones,
        mock_completion,
        mock_grade_factory,
        mock_overview,
        user,
        course_key_str,
        course_key,
        mock_course_grade,
        mock_course_overview,
    ):
        """
        GIVEN user has only 50% completion (below 95% threshold)
        AND user has passing grade
        WHEN check_and_fulfill_course_milestone is called
        THEN it returns success=False with reason 'insufficient_completion'
        AND milestone is not fulfilled
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_completion.return_value = {
            'complete_count': 5,
            'incomplete_count': 5,
            'locked_count': 0,
        }
        mock_overview.return_value = mock_course_overview
        mock_grade_factory.return_value.read.return_value = mock_course_grade

        result = check_and_fulfill_course_milestone(user.id, course_key_str)

        assert result['success'] is False
        assert result['reason'] == 'insufficient_completion'
        assert result['completion_percent'] == 50.0
        assert result['grade_percent'] == 85.0
        assert result['has_passing_grade'] is True
        mock_milestones.fulfill_course_milestone.assert_not_called()

    @patch('learning_paths.tasks.get_course_overview_or_none')
    @patch('learning_paths.tasks.CourseGradeFactory')
    @patch('learning_paths.tasks.get_course_blocks_completion_summary')
    @patch('learning_paths.tasks.milestones_helpers')
    def test_not_passing_grade(
        self,
        mock_milestones,
        mock_completion,
        mock_grade_factory,
        mock_overview,
        user,
        course_key_str,
        course_key,
        mock_completion_summary,
        mock_course_overview,
    ):
        """
        GIVEN user has 100% completion
        AND user has failing grade (50%)
        WHEN check_and_fulfill_course_milestone is called
        THEN it returns success=False with reason 'not_passing'
        AND milestone is not fulfilled
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_completion.return_value = mock_completion_summary

        failing_grade = Mock()
        failing_grade.percent = 0.50
        failing_grade.passed = False

        mock_overview.return_value = mock_course_overview
        mock_grade_factory.return_value.read.return_value = failing_grade

        result = check_and_fulfill_course_milestone(user.id, course_key_str)

        assert result['success'] is False
        assert result['reason'] == 'not_passing'
        assert result['completion_percent'] == 100.0
        assert result['grade_percent'] == 50.0
        assert result['has_passing_grade'] is False
        mock_milestones.fulfill_course_milestone.assert_not_called()

    @patch('learning_paths.tasks.get_course_overview_or_none')
    @patch('learning_paths.tasks.CourseGradeFactory')
    @patch('learning_paths.tasks.get_course_blocks_completion_summary')
    @patch('learning_paths.tasks.milestones_helpers')
    def test_successful_milestone_fulfillment(
        self,
        mock_milestones,
        mock_completion,
        mock_grade_factory,
        mock_overview,
        user,
        course_key_str,
        course_key,
        mock_completion_summary,
        mock_course_grade,
        mock_course_overview,
    ):
        """
        GIVEN user has 100% completion
        AND user has passing grade (85%)
        WHEN check_and_fulfill_course_milestone is called
        THEN it returns success=True with reason 'milestone_fulfilled'
        AND fulfill_course_milestone is called with correct parameters
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_completion.return_value = mock_completion_summary
        mock_overview.return_value = mock_course_overview
        mock_grade_factory.return_value.read.return_value = mock_course_grade

        result = check_and_fulfill_course_milestone(user.id, course_key_str)

        assert result['success'] is True
        assert result['reason'] == 'milestone_fulfilled'
        assert result['completion_percent'] == 100.0
        assert result['grade_percent'] == 85.0
        assert result['has_passing_grade'] is True
        mock_milestones.fulfill_course_milestone.assert_called_once()

        # Verify it was called with correct course_key and user
        call_args = mock_milestones.fulfill_course_milestone.call_args[0]
        assert str(call_args[0]) == course_key_str
        assert call_args[1].id == user.id

    @patch('learning_paths.tasks.get_course_overview_or_none')
    @patch('learning_paths.tasks.CourseGradeFactory')
    @patch('learning_paths.tasks.get_course_blocks_completion_summary')
    @patch('learning_paths.tasks.milestones_helpers')
    def test_exact_threshold_completion(
        self,
        mock_milestones,
        mock_completion,
        mock_grade_factory,
        mock_overview,
        user,
        course_key_str,
        course_key,
        mock_course_grade,
        mock_course_overview,
    ):
        """
        GIVEN user has exactly 95% completion (at threshold)
        AND user has passing grade
        WHEN check_and_fulfill_course_milestone is called
        THEN it returns success=True and fulfills milestone
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_completion.return_value = {
            'complete_count': 19,
            'incomplete_count': 1,
            'locked_count': 0,
        }
        mock_overview.return_value = mock_course_overview
        mock_grade_factory.return_value.read.return_value = mock_course_grade

        result = check_and_fulfill_course_milestone(user.id, course_key_str)

        assert result['success'] is True
        assert result['completion_percent'] == 95.0
        mock_milestones.fulfill_course_milestone.assert_called_once()

    @patch('learning_paths.tasks.get_course_overview_or_none')
    @patch('learning_paths.tasks.CourseGradeFactory')
    @patch('learning_paths.tasks.get_course_blocks_completion_summary')
    @patch('learning_paths.tasks.milestones_helpers')
    def test_just_below_threshold_completion(
        self,
        mock_milestones,
        mock_completion,
        mock_grade_factory,
        mock_overview,
        user,
        course_key_str,
        course_key,
        mock_course_grade,
        mock_course_overview,
    ):
        """
        GIVEN user has 94.9% completion (just below threshold)
        AND user has passing grade
        WHEN check_and_fulfill_course_milestone is called
        THEN it returns success=False with insufficient_completion
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_completion.return_value = {
            'complete_count': 94,
            'incomplete_count': 6,
            'locked_count': 0,
        }
        mock_overview.return_value = mock_course_overview
        mock_grade_factory.return_value.read.return_value = mock_course_grade

        result = check_and_fulfill_course_milestone(user.id, course_key_str)

        assert result['success'] is False
        assert result['reason'] == 'insufficient_completion'
        assert result['completion_percent'] == 94.0
        mock_milestones.fulfill_course_milestone.assert_not_called()

    @patch('learning_paths.tasks.get_course_overview_or_none')
    @patch('learning_paths.tasks.CourseGradeFactory')
    @patch('learning_paths.tasks.get_course_blocks_completion_summary')
    @patch('learning_paths.tasks.milestones_helpers')
    def test_with_locked_units(
        self,
        mock_milestones,
        mock_completion,
        mock_grade_factory,
        mock_overview,
        user,
        course_key_str,
        course_key,
        mock_course_grade,
        mock_course_overview,
    ):
        """
        GIVEN user has completed 10 out of 10 available units
        AND there are 2 locked units
        WHEN check_and_fulfill_course_milestone is called
        THEN completion is calculated as 10/12 = 83.33%
        AND milestone is not fulfilled (below 95%)
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_completion.return_value = {
            'complete_count': 10,
            'incomplete_count': 0,
            'locked_count': 2,
        }
        mock_overview.return_value = mock_course_overview
        mock_grade_factory.return_value.read.return_value = mock_course_grade

        result = check_and_fulfill_course_milestone(user.id, course_key_str)

        assert result['success'] is False
        assert result['reason'] == 'insufficient_completion'
        assert result['completion_percent'] == 83.0  # rounded
        mock_milestones.fulfill_course_milestone.assert_not_called()

    @patch('learning_paths.tasks.get_course_overview_or_none')
    @patch('learning_paths.tasks.CourseGradeFactory')
    @patch('learning_paths.tasks.get_course_blocks_completion_summary')
    @patch('learning_paths.tasks.milestones_helpers')
    def test_no_completion_summary(
        self,
        mock_milestones,
        mock_completion,
        mock_grade_factory,
        mock_overview,
        user,
        course_key_str,
        course_key,
        mock_course_grade,
        mock_course_overview,
    ):
        """
        GIVEN completion summary returns None or empty
        WHEN check_and_fulfill_course_milestone is called
        THEN completion_percent is 0
        AND milestone is not fulfilled
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_completion.return_value = None
        mock_overview.return_value = mock_course_overview
        mock_grade_factory.return_value.read.return_value = mock_course_grade

        result = check_and_fulfill_course_milestone(user.id, course_key_str)

        assert result['success'] is False
        assert result['reason'] == 'insufficient_completion'
        assert result['completion_percent'] == 0
        mock_milestones.fulfill_course_milestone.assert_not_called()


@pytest.mark.django_db
class TestSignalHandlerExecutionModes:
    """Tests for signal handler with sync and async execution modes."""

    @patch('learning_paths.receivers.milestones_helpers')
    def test_signal_skips_incomplete_blocks(self, mock_milestones, user):
        """
        GIVEN a block completion with less than 100% completion
        WHEN signal handler is triggered
        THEN it returns early without checking execution mode
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True

        block_completion = Mock()
        block_completion.completion = 0.5
        block_completion.user = user

        # Should return early, no execution mode check needed
        fulfill_milestone_on_block_completion(
            sender=Mock(),
            instance=block_completion,
            created=False
        )

        # Prerequisites check should not even be called
        mock_milestones.is_prerequisite_courses_enabled.assert_not_called()

    @patch('learning_paths.receivers.check_and_fulfill_course_milestone')
    @patch('learning_paths.receivers.settings')
    @patch('learning_paths.receivers.milestones_helpers')
    def test_sync_mode_executes_inline(
        self,
        mock_milestones,
        mock_settings,
        mock_check_fulfill,
        user,
        course_key,
    ):
        """
        GIVEN LEARNING_PATHS_MILESTONE_MODE is set to 'sync'
        WHEN signal handler is triggered with complete block
        THEN check_and_fulfill_course_milestone is called directly (inline)
        AND no Celery task is dispatched
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_settings.LEARNING_PATHS_MILESTONE_MODE = 'sync'
        mock_check_fulfill.return_value = {
            'success': True,
            'reason': 'milestone_fulfilled',
            'completion_percent': 100.0,
            'grade_percent': 85.0,
            'has_passing_grade': True,
        }

        block_completion = Mock()
        block_completion.completion = 1.0
        block_completion.user = user
        block_completion.block_key = Mock()
        block_completion.block_key.course_key = course_key

        fulfill_milestone_on_block_completion(
            sender=Mock(),
            instance=block_completion,
            created=False
        )

        # Verify inline execution
        mock_check_fulfill.assert_called_once_with(user.id, str(course_key))

    @patch('learning_paths.receivers.fulfill_course_milestone_task')
    @patch('learning_paths.receivers.settings')
    @patch('learning_paths.receivers.milestones_helpers')
    def test_async_mode_dispatches_celery_task(
        self,
        mock_milestones,
        mock_settings,
        mock_task,
        user,
        course_key,
    ):
        """
        GIVEN LEARNING_PATHS_MILESTONE_MODE is set to 'async'
        WHEN signal handler is triggered with complete block
        THEN Celery task is dispatched with apply_async
        AND business logic is not executed inline
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_settings.LEARNING_PATHS_MILESTONE_MODE = 'async'

        block_completion = Mock()
        block_completion.completion = 1.0
        block_completion.user = user
        block_completion.block_key = Mock()
        block_completion.block_key.course_key = course_key

        fulfill_milestone_on_block_completion(
            sender=Mock(),
            instance=block_completion,
            created=False
        )

        # Verify Celery task dispatched
        mock_task.apply_async.assert_called_once_with(
            args=[user.id, str(course_key)],
            countdown=5,
        )

    @patch('learning_paths.receivers.check_and_fulfill_course_milestone')
    @patch('learning_paths.receivers.settings')
    @patch('learning_paths.receivers.milestones_helpers')
    def test_sync_mode_handles_exception(
        self,
        mock_milestones,
        mock_settings,
        mock_check_fulfill,
        user,
        course_key,
    ):
        """
        GIVEN LEARNING_PATHS_MILESTONE_MODE is 'sync'
        AND check_and_fulfill_course_milestone raises an exception
        WHEN signal handler is triggered
        THEN exception is caught and logged, but does not propagate
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_settings.LEARNING_PATHS_MILESTONE_MODE = 'sync'
        mock_check_fulfill.side_effect = Exception("DB error")

        block_completion = Mock()
        block_completion.completion = 1.0
        block_completion.user = user
        block_completion.block_key = Mock()
        block_completion.block_key.course_key = course_key

        # Should not raise exception
        fulfill_milestone_on_block_completion(
            sender=Mock(),
            instance=block_completion,
            created=False
        )

        # Verify function was called
        mock_check_fulfill.assert_called_once()

    @patch('learning_paths.receivers.fulfill_course_milestone_task')
    @patch('learning_paths.receivers.settings')
    @patch('learning_paths.receivers.milestones_helpers')
    def test_async_mode_handles_exception(
        self,
        mock_milestones,
        mock_settings,
        mock_task,
        user,
        course_key,
    ):
        """
        GIVEN LEARNING_PATHS_MILESTONE_MODE is 'async'
        AND apply_async raises an exception
        WHEN signal handler is triggered
        THEN exception is caught and logged, but does not propagate
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_settings.LEARNING_PATHS_MILESTONE_MODE = 'async'
        mock_task.apply_async.side_effect = Exception("Celery connection error")

        block_completion = Mock()
        block_completion.completion = 1.0
        block_completion.user = user
        block_completion.block_key = Mock()
        block_completion.block_key.course_key = course_key

        # Should not raise exception
        fulfill_milestone_on_block_completion(
            sender=Mock(),
            instance=block_completion,
            created=False
        )

        # Verify task dispatch was attempted
        mock_task.apply_async.assert_called_once()

    @patch('learning_paths.tasks.get_course_overview_or_none')
    @patch('learning_paths.tasks.CourseGradeFactory')
    @patch('learning_paths.tasks.get_course_blocks_completion_summary')
    @patch('learning_paths.tasks.milestones_helpers')
    def test_no_course_overview(
        self,
        mock_milestones,
        mock_completion,
        mock_grade_factory,
        mock_overview,
        user,
        course_key_str,
        mock_completion_summary,
    ):
        """
        GIVEN course overview is not found
        WHEN check_and_fulfill_course_milestone is called
        THEN grade_percent is 0 and has_passing_grade is False
        AND milestone is not fulfilled
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_completion.return_value = mock_completion_summary
        mock_overview.return_value = None

        result = check_and_fulfill_course_milestone(user.id, course_key_str)

        assert result['success'] is False
        assert result['reason'] == 'not_passing'
        assert result['grade_percent'] == 0
        assert result['has_passing_grade'] is False
        mock_milestones.fulfill_course_milestone.assert_not_called()

    @patch('learning_paths.tasks.get_course_overview_or_none')
    @patch('learning_paths.tasks.CourseGradeFactory')
    @patch('learning_paths.tasks.get_course_blocks_completion_summary')
    @patch('learning_paths.tasks.milestones_helpers')
    def test_no_course_grade(
        self,
        mock_milestones,
        mock_completion,
        mock_grade_factory,
        mock_overview,
        user,
        course_key_str,
        mock_completion_summary,
        mock_course_overview,
    ):
        """
        GIVEN course grade returns None
        WHEN check_and_fulfill_course_milestone is called
        THEN grade_percent is 0 and has_passing_grade is False
        AND milestone is not fulfilled
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_completion.return_value = mock_completion_summary
        mock_overview.return_value = mock_course_overview
        mock_grade_factory.return_value.read.return_value = None

        result = check_and_fulfill_course_milestone(user.id, course_key_str)

        assert result['success'] is False
        assert result['reason'] == 'not_passing'
        assert result['grade_percent'] == 0
        assert result['has_passing_grade'] is False
        mock_milestones.fulfill_course_milestone.assert_not_called()

    @patch('learning_paths.tasks.get_course_overview_or_none')
    @patch('learning_paths.tasks.CourseGradeFactory')
    @patch('learning_paths.tasks.get_course_blocks_completion_summary')
    @patch('learning_paths.tasks.milestones_helpers')
    def test_milestone_fulfillment_raises_exception(
        self,
        mock_milestones,
        mock_completion,
        mock_grade_factory,
        mock_overview,
        user,
        course_key_str,
        mock_completion_summary,
        mock_course_grade,
        mock_course_overview,
    ):
        """
        GIVEN user meets all requirements
        AND fulfill_course_milestone raises an exception
        WHEN check_and_fulfill_course_milestone is called
        THEN the exception propagates for Celery retry logic
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_completion.return_value = mock_completion_summary
        mock_overview.return_value = mock_course_overview
        mock_grade_factory.return_value.read.return_value = mock_course_grade
        mock_milestones.fulfill_course_milestone.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            check_and_fulfill_course_milestone(user.id, course_key_str)

    @patch('learning_paths.tasks.get_course_overview_or_none')
    @patch('learning_paths.tasks.CourseGradeFactory')
    @patch('learning_paths.tasks.get_course_blocks_completion_summary')
    @patch('learning_paths.tasks.milestones_helpers')
    def test_zero_total_units(
        self,
        mock_milestones,
        mock_completion,
        mock_grade_factory,
        mock_overview,
        user,
        course_key_str,
        mock_course_grade,
        mock_course_overview,
    ):
        """
        GIVEN completion summary shows 0 total units
        WHEN check_and_fulfill_course_milestone is called
        THEN completion_percent is 0 (avoids division by zero)
        AND milestone is not fulfilled
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_completion.return_value = {
            'complete_count': 0,
            'incomplete_count': 0,
            'locked_count': 0,
        }
        mock_overview.return_value = mock_course_overview
        mock_grade_factory.return_value.read.return_value = mock_course_grade

        result = check_and_fulfill_course_milestone(user.id, course_key_str)

        assert result['success'] is False
        assert result['reason'] == 'insufficient_completion'
        assert result['completion_percent'] == 0
        mock_milestones.fulfill_course_milestone.assert_not_called()


@pytest.mark.django_db
class TestSignalHandlerExecutionModes:
    """Tests for signal handler with sync and async execution modes."""

    @patch('learning_paths.receivers.milestones_helpers')
    def test_signal_skips_incomplete_blocks(self, mock_milestones, user):
        """
        GIVEN a block completion with less than 100% completion
        WHEN signal handler is triggered
        THEN it returns early without checking execution mode
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True

        block_completion = Mock()
        block_completion.completion = 0.5
        block_completion.user = user

        # Should return early, no execution mode check needed
        fulfill_milestone_on_block_completion(
            sender=Mock(),
            instance=block_completion,
            created=False
        )

        # Prerequisites check should not even be called
        mock_milestones.is_prerequisite_courses_enabled.assert_not_called()

    @patch('learning_paths.receivers.check_and_fulfill_course_milestone')
    @patch('learning_paths.receivers.settings')
    @patch('learning_paths.receivers.milestones_helpers')
    def test_sync_mode_executes_inline(
        self,
        mock_milestones,
        mock_settings,
        mock_check_fulfill,
        user,
        course_key,
    ):
        """
        GIVEN LEARNING_PATHS_MILESTONE_MODE is set to 'sync'
        WHEN signal handler is triggered with complete block
        THEN check_and_fulfill_course_milestone is called directly (inline)
        AND no Celery task is dispatched
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_settings.LEARNING_PATHS_MILESTONE_MODE = 'sync'
        mock_check_fulfill.return_value = {
            'success': True,
            'reason': 'milestone_fulfilled',
            'completion_percent': 100.0,
            'grade_percent': 85.0,
            'has_passing_grade': True,
        }

        block_completion = Mock()
        block_completion.completion = 1.0
        block_completion.user = user
        block_completion.block_key = Mock()
        block_completion.block_key.course_key = course_key

        fulfill_milestone_on_block_completion(
            sender=Mock(),
            instance=block_completion,
            created=False
        )

        # Verify inline execution
        mock_check_fulfill.assert_called_once_with(user.id, str(course_key))

    @patch('learning_paths.receivers.fulfill_course_milestone_task')
    @patch('learning_paths.receivers.settings')
    @patch('learning_paths.receivers.milestones_helpers')
    def test_async_mode_dispatches_celery_task(
        self,
        mock_milestones,
        mock_settings,
        mock_task,
        user,
        course_key,
    ):
        """
        GIVEN LEARNING_PATHS_MILESTONE_MODE is set to 'async'
        WHEN signal handler is triggered with complete block
        THEN Celery task is dispatched with apply_async
        AND business logic is not executed inline
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_settings.LEARNING_PATHS_MILESTONE_MODE = 'async'

        block_completion = Mock()
        block_completion.completion = 1.0
        block_completion.user = user
        block_completion.block_key = Mock()
        block_completion.block_key.course_key = course_key

        fulfill_milestone_on_block_completion(
            sender=Mock(),
            instance=block_completion,
            created=False
        )

        # Verify Celery task dispatched
        mock_task.apply_async.assert_called_once_with(
            args=[user.id, str(course_key)],
            countdown=5,
        )

    @patch('learning_paths.receivers.check_and_fulfill_course_milestone')
    @patch('learning_paths.receivers.settings')
    @patch('learning_paths.receivers.milestones_helpers')
    def test_sync_mode_handles_exception(
        self,
        mock_milestones,
        mock_settings,
        mock_check_fulfill,
        user,
        course_key,
    ):
        """
        GIVEN LEARNING_PATHS_MILESTONE_MODE is 'sync'
        AND check_and_fulfill_course_milestone raises an exception
        WHEN signal handler is triggered
        THEN exception is caught and logged, but does not propagate
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_settings.LEARNING_PATHS_MILESTONE_MODE = 'sync'
        mock_check_fulfill.side_effect = Exception("DB error")

        block_completion = Mock()
        block_completion.completion = 1.0
        block_completion.user = user
        block_completion.block_key = Mock()
        block_completion.block_key.course_key = course_key

        # Should not raise exception
        fulfill_milestone_on_block_completion(
            sender=Mock(),
            instance=block_completion,
            created=False
        )

        # Verify function was called
        mock_check_fulfill.assert_called_once()

    @patch('learning_paths.receivers.fulfill_course_milestone_task')
    @patch('learning_paths.receivers.settings')
    @patch('learning_paths.receivers.milestones_helpers')
    def test_async_mode_handles_exception(
        self,
        mock_milestones,
        mock_settings,
        mock_task,
        user,
        course_key,
    ):
        """
        GIVEN LEARNING_PATHS_MILESTONE_MODE is 'async'
        AND apply_async raises an exception
        WHEN signal handler is triggered
        THEN exception is caught and logged, but does not propagate
        """
        mock_milestones.is_prerequisite_courses_enabled.return_value = True
        mock_settings.LEARNING_PATHS_MILESTONE_MODE = 'async'
        mock_task.apply_async.side_effect = Exception("Celery connection error")

        block_completion = Mock()
        block_completion.completion = 1.0
        block_completion.user = user
        block_completion.block_key = Mock()
        block_completion.block_key.course_key = course_key

        # Should not raise exception
        fulfill_milestone_on_block_completion(
            sender=Mock(),
            instance=block_completion,
            created=False
        )

        # Verify task dispatch was attempted
        mock_task.apply_async.assert_called_once()
