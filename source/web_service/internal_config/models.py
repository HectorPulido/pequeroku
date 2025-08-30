from django.db import models


class Config(models.Model):
    """
    Model for Configurations flags
    """

    name = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.name}: {str(self.value)[:20]}"
