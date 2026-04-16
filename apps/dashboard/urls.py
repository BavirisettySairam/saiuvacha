from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard, name='index'),
    path('unflag/<int:message_id>/', views.unflag_message, name='unflag'),
]
