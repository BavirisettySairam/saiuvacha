"""
ASGI config for sai-uvacha.

/healthz/ is handled at the ASGI level — before Django's middleware stack —
so it is immune to ALLOWED_HOSTS validation, SSL redirect, sessions, etc.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

_django_app = get_asgi_application()


async def application(scope, receive, send):
    """Thin ASGI wrapper: short-circuit /healthz/ before Django middleware."""
    if scope['type'] == 'lifespan':
        # Django doesn't support the ASGI lifespan protocol — handle it here
        # so it never reaches Django and raises ValueError.
        while True:
            message = await receive()
            if message['type'] == 'lifespan.startup':
                await send({'type': 'lifespan.startup.complete'})
            elif message['type'] == 'lifespan.shutdown':
                await send({'type': 'lifespan.shutdown.complete'})
                return

    if scope['type'] == 'http' and scope.get('path') == '/healthz/':
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [(b'content-type', b'application/json')],
        })
        await send({
            'type': 'http.response.body',
            'body': b'{"status":"ok"}',
        })
        return

    await _django_app(scope, receive, send)
