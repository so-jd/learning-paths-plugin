"""
Views for Learning Path certificates.
"""

import logging

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from learning_paths.models import LearningPath

from ..serializers import LearningPathCertificateStatusSerializer

logger = logging.getLogger(__name__)

User = get_user_model()


class LearningPathCertificateStatusView(APIView):
    """
    API View to retrieve certificate status and eligibility for a learning path.

    This endpoint returns:
    - Whether the user is eligible for a certificate
    - Current progress and grade information
    - Whether a certificate has been awarded
    - Certificate download URL if awarded
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, learning_path_key_str: str):
        """
        Get certificate status and eligibility for the current user in a learning path.

        Query params:
            username (optional): For staff only - check certificate status for a specific user

        Returns:
            {
                "learning_path_key": "path-v1:...",
                "learning_path_uuid": "uuid",
                "username": "learner123",
                "is_eligible": true/false,
                "progress": 0.95,
                "required_completion": 0.80,
                "grade": 0.85,
                "required_grade": 0.75,
                "certificate_awarded": true/false,
                "certificate_uuid": "uuid" or null,
                "certificate_url": "https://..." or null,
                "reason": "eligible" or "insufficient_completion" etc
            }
        """
        # Get the learning path
        learning_path = get_object_or_404(
            LearningPath.objects.get_paths_visible_to_user(request.user),
            key=learning_path_key_str,
        )

        # Determine which user to check (staff can check for others)
        username = request.query_params.get("username")
        if username and request.user.is_staff:
            user = get_object_or_404(User, username=username)
        elif username and not request.user.is_staff:
            # Non-staff users can only check their own status
            raise PermissionDenied("You can only check your own certificate status.")
        else:
            user = request.user

        # Check if credentials feature is enabled
        if not getattr(settings, 'LEARNING_PATHS_ENABLE_CREDENTIALS', False):
            return Response(
                {
                    "learning_path_key": learning_path_key_str,
                    "learning_path_uuid": str(learning_path.uuid),
                    "username": user.username,
                    "is_eligible": False,
                    "progress": 0.0,
                    "required_completion": 0.80,
                    "grade": 0.0,
                    "required_grade": 0.75,
                    "certificate_awarded": False,
                    "certificate_uuid": None,
                    "certificate_url": None,
                    "reason": "credentials_disabled",
                },
                status=status.HTTP_200_OK,
            )

        # Check eligibility using the credentials module
        from learning_paths.credentials import check_learning_path_completion_for_credential

        is_eligible, eligibility_data = check_learning_path_completion_for_credential(user, learning_path)

        # Check if certificate has been awarded
        certificate_awarded = False
        certificate_uuid = None
        certificate_url = None

        try:
            credentials_api_url = getattr(settings, 'CREDENTIALS_SERVICE_URL', settings.LMS_ROOT_URL)
            list_url = f"{credentials_api_url}/api/v2/credentials/"

            response = requests.get(
                list_url,
                params={
                    'username': user.username,
                    'program_uuid': str(learning_path.uuid),
                    'status': 'awarded',
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            if data.get('results') and len(data['results']) > 0:
                credential = data['results'][0]
                certificate_awarded = True
                certificate_uuid = credential.get('uuid')
                # Build certificate URL
                certificate_url = f"{credentials_api_url}/credentials/{certificate_uuid}/"

        except Exception as e:
            logger.warning(
                "Failed to check certificate award status for user %s in learning path %s: %s",
                user.username,
                learning_path_key_str,
                str(e),
            )
            # Continue with certificate_awarded = False if check fails

        # Build response
        response_data = {
            "learning_path_key": learning_path_key_str,
            "learning_path_uuid": str(learning_path.uuid),
            "username": user.username,
            "is_eligible": is_eligible,
            "progress": eligibility_data.get('progress', 0.0),
            "required_completion": eligibility_data.get('required_completion', 0.80),
            "grade": eligibility_data.get('grade', 0.0),
            "required_grade": eligibility_data.get('required_grade', 0.75),
            "certificate_awarded": certificate_awarded,
            "certificate_uuid": certificate_uuid,
            "certificate_url": certificate_url,
            "reason": eligibility_data.get('reason', 'unknown'),
        }

        serializer = LearningPathCertificateStatusSerializer(data=response_data)
        if serializer.is_valid():
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
