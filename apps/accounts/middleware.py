"""
Free trial middleware.

Unauthenticated users get FREE_TRIAL_LIMIT (5) queries tracked by session.
After the limit they are redirected to login.
Only applies to the SSE/ask endpoint, not to page loads.
"""

from django.conf import settings
from django.http import JsonResponse

FREE_TRIAL_KEY = 'free_trial_count'
GATED_PATHS = {'/chat/ask/'}


class FreeTrialMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in GATED_PATHS and not request.user.is_authenticated:
            count = request.session.get(FREE_TRIAL_KEY, 0)
            limit = getattr(settings, 'FREE_TRIAL_LIMIT', 5)
            if count >= limit:
                return JsonResponse(
                    {
                        'error': 'trial_limit_reached',
                        'message': (
                            'You have used your 5 free questions. '
                            'Please sign in to continue receiving Swami\'s guidance.'
                        ),
                        'login_url': '/accounts/login/',
                    },
                    status=403,
                )
        return self.get_response(request)
