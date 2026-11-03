from django.urls import path
from . import views

app_name = 'appointments'

urlpatterns = [
    path('', views.appointment_list, name='list'),
    path('book/', views.appointment_create, name='create'),
    path('<int:pk>/status/<str:status>/', views.appointment_set_status, name='set_status'),
]
