from django.urls import path
from . import views

app_name = 'patients'

urlpatterns = [
    path('', views.patient_list, name='list'),
    path('register/', views.patient_register, name='register'),
    path('<int:pk>/', views.patient_detail, name='detail'),
]
