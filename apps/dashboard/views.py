from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.shortcuts import render

from apps.chat.models import Conversation, Message


@staff_member_required
def dashboard(request):
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timezone.timedelta(days=7)

    total_messages = Message.objects.filter(role='user').count()
    today_messages = Message.objects.filter(role='user', created_at__gte=today_start).count()
    week_messages = Message.objects.filter(role='user', created_at__gte=week_start).count()

    total_users = Conversation.objects.values('user').distinct().count()
    total_conversations = Conversation.objects.count()

    flagged = (
        Message.objects
        .filter(flagged=True)
        .select_related('conversation', 'conversation__user')
        .order_by('-created_at')[:50]
    )

    return render(request, 'dashboard/index.html', {
        'total_messages': total_messages,
        'today_messages': today_messages,
        'week_messages': week_messages,
        'total_users': total_users,
        'total_conversations': total_conversations,
        'flagged': flagged,
    })


@staff_member_required
@require_POST
def unflag_message(request, message_id):
    msg = get_object_or_404(Message, pk=message_id)
    msg.flagged = False
    msg.save(update_fields=['flagged'])
    return JsonResponse({'unflagged': True})
