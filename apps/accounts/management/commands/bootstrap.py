"""
One-shot bootstrap command run by Railway's preDeployCommand.
Safe to run on every deploy — all operations are idempotent.
"""
import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site


class Command(BaseCommand):
    help = "Create superuser and set Site domain (idempotent)."

    def handle(self, *args, **options):
        self._setup_site()
        self._create_superuser()

    def _setup_site(self):
        domain = os.environ.get("ALLOWED_HOSTS", "localhost").split(",")[0].strip()
        site, created = Site.objects.update_or_create(
            id=1,
            defaults={"domain": domain, "name": "Sai Uvacha"},
        )
        verb = "Created" if created else "Updated"
        self.stdout.write(f"{verb} Site → {domain}")

    def _create_superuser(self):
        User = get_user_model()
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        if not all([username, email, password]):
            self.stdout.write("Superuser env vars not set — skipping.")
            return

        user = User.objects.filter(email=email).first()
        if user:
            # Always sync password + staff flags in case they changed
            user.set_password(password)
            user.is_staff = True
            user.is_superuser = True
            user.save(update_fields=['password', 'is_staff', 'is_superuser'])
            self.stdout.write(f"Superuser '{email}' updated.")
        else:
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(f"Superuser '{email}' created.")
