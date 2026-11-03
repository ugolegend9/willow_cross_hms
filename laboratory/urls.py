from django.urls import path
from . import views

app_name = 'laboratory'

urlpatterns = [
    path('', views.lab_queue, name='queue'),
    path('order/<int:patient_pk>/', views.order_test, name='order'),
    path('<int:pk>/collect/', views.collect_sample, name='collect'),
    path('<int:pk>/result/', views.enter_result, name='result'),
    path('<int:pk>/cancel/', views.cancel_order, name='cancel'),
]
