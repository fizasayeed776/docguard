from django.contrib import admin

from .models import Artifact, Source

admin.site.register(Source)
admin.site.register(Artifact)
