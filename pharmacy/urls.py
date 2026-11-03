from django.urls import path
from . import views

app_name = 'pharmacy'

urlpatterns = [
    path('', views.pharmacy_queue, name='queue'),
    path('inventory/', views.inventory, name='inventory'),
    path('dispense/patient/<int:patient_pk>/', views.dispense, name='dispense'),
    path('dispense/patient/<int:patient_pk>/prescription/<int:prescription_pk>/', views.dispense, name='dispense_from_prescription'),
]
