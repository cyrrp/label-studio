"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license.
"""
from django.urls import include, path

from . import api

app_name = 'comments'

_api_urlpatterns = [
    path('', api.CommentListAPI.as_view(), name='comment-list'),
    path('<int:pk>/', api.CommentAPI.as_view(), name='comment-detail'),
]

urlpatterns = [
    path('api/comments/', include((_api_urlpatterns, app_name), namespace='api-comments')),
]
