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

        if User.objects.filter(username=username).exists():
            self.stdout.write(f"Superuser '{username}' already exists — skipping.")
            return

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(f"Superuser '{username}' created.")
