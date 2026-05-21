"""
monitor/authentication.py
-------------------------
Simple API key authentication for the POST endpoint.

Lambda sends:  Authorization: Bearer <API_KEY>
This permission class checks that header against the DJANGO_API_KEY setting.
"""

from rest_framework.permissions import BasePermission
from django.conf import settings


class HasValidAPIKey(BasePermission):
    """
    Allows access only if the request contains a valid Bearer API key.

    The API key is compared against settings.DJANGO_API_KEY.
    Used on the POST /api/readings/ endpoint to ensure only Lambda
    (or authorised clients) can write data.
    """

    message = "Invalid or missing API key."

    def has_permission(self, request, view):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")

        if not auth_header.startswith("Bearer "):
            return False

        token = auth_header[7:].strip()
        return token == settings.DJANGO_API_KEY
