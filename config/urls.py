from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse


def health(request):
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path('health/', health),
    path('healthz/', health),   # Railway healthcheck alias
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
    path('', include('apps.chat.urls')),
]
