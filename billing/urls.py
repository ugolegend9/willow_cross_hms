from django.urls import path
from . import views

app_name = 'billing'

urlpatterns = [
    path('', views.invoice_list, name='list'),
    path('new/', views.invoice_create, name='create'),
    path('<int:pk>/', views.invoice_detail, name='detail'),
    path('<int:pk>/print/', views.invoice_print, name='print'),
]
