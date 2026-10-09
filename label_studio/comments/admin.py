"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license.
"""
from comments.models import Comment
from django.contrib import admin


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('id', 'short_text', 'annotation', 'task', 'project', 'created_by', 'is_resolved', 'created_at')
    list_filter = ('is_resolved', 'project')
    search_fields = ('text', 'created_by__email')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('annotation', 'draft', 'task', 'project', 'created_by', 'updated_by')

    def short_text(self, obj):
        return (obj.text[:80] + '...') if obj.text and len(obj.text) > 80 else obj.text

    short_text.short_description = 'Text'
