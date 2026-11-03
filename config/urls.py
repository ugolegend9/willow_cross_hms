from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('patients/', include('patients.urls')),
    path('ehr/', include('ehr.urls')),
    path('appointments/', include('appointments.urls')),
    path('opd/', include('opd.urls')),
    path('ipd/', include('ipd.urls')),
    path('billing/', include('billing.urls')),
    path('pharmacy/', include('pharmacy.urls')),
    path('laboratory/', include('laboratory.urls')),
    path('', include('core.urls')),
]
