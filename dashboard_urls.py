from django.urls import path
from dashboard_views import (
    index_view,
    favicon_view,
    api_status_view,
    api_toggle_view,
    api_config_view,
    api_backtest_run_view,
)

urlpatterns = [
    path('', index_view, name='index'),
    path('favicon.ico', favicon_view, name='favicon'),
    path('api/status/', api_status_view, name='api_status'),
    path('api/toggle/', api_toggle_view, name='api_toggle'),
    path('api/config/', api_config_view, name='api_config'),
    path('api/backtest/', api_backtest_run_view, name='api_backtest'),
]
