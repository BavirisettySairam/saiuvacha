from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    path('', views.landing, name='landing'),
    path('chat/', views.chat_index, name='index'),
    path('chat/ask/', views.ask, name='ask'),
    path('chat/new/', views.new_conversation, name='new'),
    path('chat/flag/<int:message_id>/', views.flag_message, name='flag'),
]
