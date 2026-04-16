from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('email', 'username', 'language_preference', 'query_count', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (
        ('Sai Uvacha', {'fields': ('language_preference', 'query_count')}),
    )
