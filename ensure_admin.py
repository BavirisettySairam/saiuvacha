"""
Standalone script — run by Railway preDeployCommand to ensure the superuser exists.
Does not use Django management command framework to avoid silent failures.
"""
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402 — must be after setup()

email    = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "")

if not all([email, password, username]):
    print("ensure_admin: ERROR — DJANGO_SUPERUSER_EMAIL / PASSWORD / USERNAME not set", flush=True)
    sys.exit(1)

User = get_user_model()
user = User.objects.filter(email=email).first()

if user:
    user.set_password(password)
    user.username   = username
    user.is_staff   = True
    user.is_superuser = True
    user.is_active  = True
    user.save()
    print(f"ensure_admin: updated superuser '{email}'", flush=True)
else:
    User.objects.create_superuser(username=username, email=email, password=password)
    print(f"ensure_admin: created superuser '{email}'", flush=True)
