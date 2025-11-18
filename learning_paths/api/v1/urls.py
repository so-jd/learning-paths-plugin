"""API v1 URLs."""

from django.urls import path, re_path
from rest_framework import routers

from learning_paths.api.v1.views import (
    AllObjectTagsView,
    BulkEnrollGroupToCourseView,
    BulkEnrollView,
    CoursePrerequisitesView,
    GroupCourseAssignmentViewSet,
    GroupsListView,
    LearningPathAsProgramViewSet,
    LearningPathCertificateStatusView,
    LearningPathCourseEnrollmentView,
    LearningPathEnrollmentView,
    LearningPathUserGradeView,
    LearningPathUserProgressView,
    LearningPathViewSet,
    ListEnrollmentsView,
    SyncGroupEnrollmentsView,
)
from learning_paths.keys import COURSE_KEY_URL_PATTERN, LEARNING_PATH_URL_PATTERN

router = routers.SimpleRouter()
router.register(r"programs", LearningPathAsProgramViewSet, basename="learning-path-as-program")
router.register(r"learning-paths", LearningPathViewSet, basename="learning-path")
router.register(r"group-course-assignments", GroupCourseAssignmentViewSet, basename="group-course-assignment")

urlpatterns = router.urls + [
    re_path(
        rf"{LEARNING_PATH_URL_PATTERN}/progress/",
        LearningPathUserProgressView.as_view(),
        name="learning-path-progress",
    ),
    re_path(
        rf"{LEARNING_PATH_URL_PATTERN}/grade/",
        LearningPathUserGradeView.as_view(),
        name="learning-path-grade",
    ),
    re_path(
        rf"{LEARNING_PATH_URL_PATTERN}/certificate/",
        LearningPathCertificateStatusView.as_view(),
        name="learning-path-certificate",
    ),
    re_path(
        rf"{LEARNING_PATH_URL_PATTERN}/enrollments/$",
        LearningPathEnrollmentView.as_view(),
        name="learning-path-enrollments",
    ),
    path(
        "enrollments/",
        ListEnrollmentsView.as_view(),
        name="list-enrollments",
    ),
    path(
        "enrollments/bulk-enroll/",
        BulkEnrollView.as_view(),
        name="bulk-enroll",
    ),
    path(
        "groups/",
        GroupsListView.as_view(),
        name="groups-list",
    ),
    re_path(
        rf"{LEARNING_PATH_URL_PATTERN}/enrollments/{COURSE_KEY_URL_PATTERN}/",
        LearningPathCourseEnrollmentView.as_view(),
        name="learning-path-course-enroll",
    ),
    path(
        "all_object_tags/",
        AllObjectTagsView.as_view(),
        name="all-object-tags",
    ),
    path(
        "group-enrollments/bulk-enroll/",
        BulkEnrollGroupToCourseView.as_view(),
        name="group-bulk-enroll",
    ),
    path(
        "group-enrollments/sync/",
        SyncGroupEnrollmentsView.as_view(),
        name="group-enrollment-sync",
    ),
    re_path(
        rf"courses/{COURSE_KEY_URL_PATTERN}/prerequisites/$",
        CoursePrerequisitesView.as_view(),
        name="course-prerequisites",
    ),
]
