from django.urls import path
from . import views

app_name = 'ehr'

urlpatterns = [
    path('patient/<int:pk>/', views.patient_ehr, name='patient_ehr'),
]
