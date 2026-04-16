from django.contrib import admin
from .models import Conversation, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'title', 'language', 'created_at', 'updated_at')
    list_filter = ('language', 'created_at')
    search_fields = ('title', 'user__email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'role', 'flagged', 'created_at')
    list_filter = ('role', 'flagged', 'created_at')
    search_fields = ('conversation__user__email',)
    readonly_fields = ('created_at',)
    actions = ['mark_unflagged']

    def mark_unflagged(self, request, queryset):
        queryset.update(flagged=False)
        self.message_user(request, f'{queryset.count()} message(s) unflagged.')
    mark_unflagged.short_description = 'Mark selected messages as not flagged'
