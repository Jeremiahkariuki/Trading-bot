from django.urls import path
from dashboard_views import (
    index_view,
    favicon_view,
    api_status_view,
    api_toggle_view,
    api_config_view,
    api_backtest_run_view,
    api_reset_balance_view,
    api_manual_trade_view,
)

urlpatterns = [
    path('', index_view, name='index'),
    path('favicon.ico', favicon_view, name='favicon'),
    path('api/status/', api_status_view, name='api_status'),
    path('api/toggle/', api_toggle_view, name='api_toggle'),
    path('api/config/', api_config_view, name='api_config'),
    path('api/backtest/', api_backtest_run_view, name='api_backtest'),
    path('api/reset_balance/', api_reset_balance_view, name='api_reset_balance'),
    path('api/manual_trade/', api_manual_trade_view, name='api_manual_trade'),
]

