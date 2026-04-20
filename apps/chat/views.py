import asyncio
import json
import logging
import threading

from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.rag import cache as response_cache
from apps.rag.pipeline import stream_ask

from .models import Conversation, Message

logger = logging.getLogger(__name__)

FREE_TRIAL_KEY = 'free_trial_count'

SAMPLE_QUESTIONS = [
    "How can I find inner peace?",
    "What is the purpose of human life?",
    "How to overcome ego and pride?",
    "What does Swami say about meditation?",
    "How to develop love for God?",
    "How to deal with grief and loss?",
]


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------

def landing(request):
    if request.user.is_authenticated:
        return redirect('chat:index')
    return render(request, 'landing.html', {'sample_questions': SAMPLE_QUESTIONS})


# ---------------------------------------------------------------------------
# Chat index
# ---------------------------------------------------------------------------

def chat_index(request):
    """Main chat page. Works for both guests (free trial) and logged-in users."""
    conversations = []
    active = None

    if request.user.is_authenticated:
        conversations = request.user.conversations.all()[:50]
        conv_id = request.GET.get('c')
        if conv_id:
            active = get_object_or_404(
                Conversation, pk=conv_id, user=request.user
            )

    trial_count = request.session.get(FREE_TRIAL_KEY, 0)
    from django.conf import settings
    trial_limit = getattr(settings, 'FREE_TRIAL_LIMIT', 5)
    trial_percent = min(100, int(trial_count / trial_limit * 100)) if trial_limit else 0

    return render(request, 'chat/index.html', {
        'conversations': conversations,
        'active': active,
        'messages': active.messages.all() if active else [],
        'trial_count': trial_count,
        'trial_limit': trial_limit,
        'trial_remaining': max(0, trial_limit - trial_count),
        'trial_percent': trial_percent,
        'sample_questions': SAMPLE_QUESTIONS,
    })


# ---------------------------------------------------------------------------
# SSE streaming endpoint
# ---------------------------------------------------------------------------

@ratelimit(key='ip', rate='20/m', method='POST', block=True)
def ask(request):
    """
    POST /chat/ask/
    Body: JSON { "query": "...", "conversation_id": null | int, "language": "en" }

    Streams the response token-by-token as Server-Sent Events.
    Gate 1 + Gate 2 run synchronously; tokens stream as they arrive.
    Rate-limited: 20 requests/minute per IP.
    """
    if request.method != 'POST':
        from django.http import JsonResponse
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        from django.http import JsonResponse
        return JsonResponse({'error': 'invalid JSON'}, status=400)

    query = (data.get('query') or '').strip()
    language = data.get('language', 'en')
    conv_id = data.get('conversation_id')

    if not query:
        from django.http import JsonResponse
        return JsonResponse({'error': 'empty query'}, status=400)

    # Increment free trial counter for guests
    if not request.user.is_authenticated:
        request.session[FREE_TRIAL_KEY] = request.session.get(FREE_TRIAL_KEY, 0) + 1
        request.session.modified = True

    # Resolve / create conversation (authenticated users only)
    conversation = None
    if request.user.is_authenticated:
        if conv_id:
            try:
                conversation = Conversation.objects.get(
                    pk=conv_id, user=request.user
                )
            except Conversation.DoesNotExist:
                pass

        if not conversation:
            conversation = Conversation.objects.create(
                user=request.user,
                language=language,
            )

        # Save user message
        Message.objects.create(
            conversation=conversation,
            role='user',
            content=query,
        )

    async def event_stream():
        full_response = []
        message_id = None
        queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def produce():
            try:
                for token in stream_ask(query, language=language):
                    loop.call_soon_threadsafe(queue.put_nowait, ('token', token))
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, ('error', exc))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, ('done', None))

        thread = threading.Thread(target=produce, daemon=True)
        thread.start()

        try:
            while True:
                kind, value = await queue.get()
                if kind == 'token':
                    full_response.append(value)
                    yield f'data: {json.dumps({"token": value})}\n\n'
                elif kind == 'error':
                    raise value
                elif kind == 'done':
                    break

            if conversation and full_response:
                response_text = ''.join(full_response)
                msg = await sync_to_async(Message.objects.create)(
                    conversation=conversation,
                    role='assistant',
                    content=response_text,
                )
                message_id = msg.pk
                if not conversation.title:
                    conversation.title = query[:80]
                    await sync_to_async(conversation.save)(update_fields=['title'])
                await sync_to_async(response_cache.store)(query, response_text)

            done_payload: dict = {'done': True}
            if conversation:
                done_payload['conversation_id'] = conversation.pk
            if message_id:
                done_payload['message_id'] = message_id
            yield f'data: {json.dumps(done_payload)}\n\n'

        except Exception as exc:
            logger.exception('stream_ask error: %s', exc)
            yield f'data: {json.dumps({"error": "Something went wrong. Please try again."})}\n\n'
        finally:
            thread.join(timeout=10)

    response = StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream',
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


# ---------------------------------------------------------------------------
# New conversation
# ---------------------------------------------------------------------------

@login_required
def new_conversation(request):
    return redirect('chat:index')


# ---------------------------------------------------------------------------
# Flag a message
# ---------------------------------------------------------------------------

@login_required
@require_POST
def flag_message(request, message_id):
    msg = get_object_or_404(
        Message,
        pk=message_id,
        conversation__user=request.user,
    )
    msg.flagged = True
    msg.save(update_fields=['flagged'])
    from django.http import JsonResponse
    return JsonResponse({'flagged': True})
