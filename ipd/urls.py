from django.urls import path
from . import views

app_name = 'ipd'

urlpatterns = [
    path('', views.bed_map, name='bed_map'),
    path('manage/', views.manage_beds, name='manage'),
    path('bed/<int:pk>/status/<str:status>/', views.bed_set_status, name='bed_status'),
    path('bed/<int:pk>/delete/', views.bed_delete, name='bed_delete'),
    path('admit/<int:patient_pk>/', views.admit_patient, name='admit'),
    path('admission/<int:pk>/', views.admission_detail, name='detail'),
    path('admission/<int:pk>/discharge/', views.discharge_admission, name='discharge'),
]
