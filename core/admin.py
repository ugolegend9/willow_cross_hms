from django.conf import settings
from django.contrib import admin

admin.site.site_header = f"{settings.HOSPITAL_NAME} — administration"
admin.site.site_title = f"{settings.HOSPITAL_NAME} admin"
admin.site.index_title = "Data administration"
