from django.urls import path

from accounts.views import CSRFTokenView, LoginView, LogoutView, MeView

app_name = 'accounts'

urlpatterns = [
    path('csrf/', CSRFTokenView.as_view(), name='csrf'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
]
