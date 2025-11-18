"""
Views for integration with other Open edX systems (tagging, etc.).
"""

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class AllObjectTagsView(APIView):
    """
    API view to get all object tags for all courses.
    Returns a mapping of object_id -> tags.

    GET /api/learning_paths/v1/all_object_tags/

    Response format:
    {
        "course-v1:Org+Course+Run": {
            "tags": [
                {
                    "value": "Python",
                    "taxonomy_id": 1,
                    "taxonomy_name": "Subjects"
                }
            ],
            "taxonomies": {
                "1": {"id": 1, "name": "Subjects"}
            }
        }
    }
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        """Fetch all object tags across all tagged objects."""
        try:
            # Import the tagging API from openedx_tagging
            from openedx_tagging.core.tagging.models import ObjectTag

            # Query all object tags
            object_tags = ObjectTag.objects.select_related(
                'tag__taxonomy'
            ).filter(
                tag__taxonomy__enabled=True
            ).all()

            # Build the response structure
            result = {}

            for obj_tag in object_tags:
                object_id = obj_tag.object_id
                taxonomy_id = obj_tag.tag.taxonomy_id
                taxonomy_name = obj_tag.tag.taxonomy.name

                # Initialize object entry if it doesn't exist
                if object_id not in result:
                    result[object_id] = {
                        'tags': [],
                        'taxonomies': {}
                    }

                # Add taxonomy info if not already added
                if str(taxonomy_id) not in result[object_id]['taxonomies']:
                    result[object_id]['taxonomies'][str(taxonomy_id)] = {
                        'id': taxonomy_id,
                        'name': taxonomy_name
                    }

                # Add tag
                result[object_id]['tags'].append({
                    'value': obj_tag.tag.value,
                    'taxonomy_id': taxonomy_id,
                    'taxonomy_name': taxonomy_name,
                })

            return Response(result)

        except ImportError:
            # If openedx_tagging is not installed, return empty
            return Response({})
        except Exception as e:
            # Return error for debugging
            return Response(
                {"error": str(e), "detail": "Failed to fetch object tags"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
