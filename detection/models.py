from django.db import models
from django.contrib.auth.models import User

class Event(models.Model):
    EVENT_CHOICES = (
        ("weapon", "Weapon Detection"),
        ("violence", "Violence Detection"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)  # 🔥 IMPORTANT

    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES)
    screenshot = models.ImageField(upload_to="screenshots/")
    video = models.FileField(upload_to="videos/")
    time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.event_type}"