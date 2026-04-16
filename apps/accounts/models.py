from django.contrib.auth.models import AbstractUser
from django.db import models

LANGUAGE_CHOICES = [
    ('en', 'English'),
    ('te', 'Telugu'),
    ('hi', 'Hindi'),
    ('ta', 'Tamil'),
    ('kn', 'Kannada'),
]


class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    language_preference = models.CharField(
        max_length=5, choices=LANGUAGE_CHOICES, default='en'
    )
    query_count = models.PositiveIntegerField(default=0)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.email
