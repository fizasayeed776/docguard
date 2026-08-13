from django.contrib import admin

from .models import Chunk, Claim, Inconsistency, ScanRun

admin.site.register(Chunk)
admin.site.register(Claim)
admin.site.register(Inconsistency)
admin.site.register(ScanRun)
