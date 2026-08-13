from django.contrib import admin

from .models import TriageRule, Workspace, WorkspaceMembership

admin.site.register(Workspace)
admin.site.register(WorkspaceMembership)
admin.site.register(TriageRule)
