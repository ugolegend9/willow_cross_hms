from django.urls import path
from . import views

app_name = 'opd'

urlpatterns = [
    path('', views.opd_queue, name='queue'),
    path('patient/<int:patient_pk>/consult/', views.opd_consult, name='consult'),
    path('patient/<int:patient_pk>/consult/<int:appointment_pk>/', views.opd_consult, name='consult_from_appointment'),
]
