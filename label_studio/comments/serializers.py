"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license.
"""
import logging

from comments.models import Comment
from core.utils.params import bool_from_request
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from tasks.models import Annotation, AnnotationDraft, Task
from users.models import User
from users.serializers import BaseUserSerializer

logger = logging.getLogger(__name__)


class CommentUserSerializer(BaseUserSerializer):
    """User snippet embedded in comments when `expand_created_by=true` is passed.

    Fields must satisfy the LSF `UserExtended` store after camelCase conversion
    (id, firstName, lastName, username, email, lastActivity, avatar, initials, phone).
    """

    class Meta:
        model = User
        fields = (
            'id',
            'first_name',
            'last_name',
            'username',
            'email',
            'last_activity',
            'avatar',
            'initials',
            'phone',
        )


class CommentSerializer(serializers.ModelSerializer):
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    updated_by = serializers.PrimaryKeyRelatedField(read_only=True)
    resolved_at = serializers.DateTimeField(read_only=True)
    # derived from the comment target on save - read only for API clients
    project = serializers.PrimaryKeyRelatedField(read_only=True)

    annotation = serializers.PrimaryKeyRelatedField(
        queryset=Annotation.objects.all(), required=False, allow_null=True
    )
    draft = serializers.PrimaryKeyRelatedField(
        queryset=AnnotationDraft.objects.all(), required=False, allow_null=True
    )
    task = serializers.PrimaryKeyRelatedField(queryset=Task.objects.all(), required=False, allow_null=True)

    region_ref = serializers.JSONField(required=False, allow_null=True)
    classifications = serializers.JSONField(required=False, allow_null=True)

    def validate(self, data):
        # a new comment must be attached to something the frontend can list it by
        if self.instance is None and not any(data.get(key) for key in ('annotation', 'draft', 'task')):
            raise ValidationError('One of "annotation", "draft" or "task" is required')
        return data

    def to_representation(self, instance):
        data = super().to_representation(instance)

        request = self.context.get('request')
        if (
            request is not None
            and instance.created_by_id
            and bool_from_request(request.query_params, 'expand_created_by', False)
        ):
            data['created_by'] = CommentUserSerializer(instance.created_by, context=self.context).data

        return data

    class Meta:
        model = Comment
        fields = (
            'id',
            'text',
            'annotation',
            'draft',
            'task',
            'project',
            'is_resolved',
            'resolved_at',
            'region_ref',
            'classifications',
            'created_by',
            'updated_by',
            'created_at',
            'updated_at',
        )
