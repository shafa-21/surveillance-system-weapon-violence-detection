from django.urls import path
from . import views

urlpatterns = [

    path("", views.login_view, name="login"),

    path("signup/", views.signup_view, name="signup"),
    path("logout/", views.logout_view, name="logout"),

    path("home/", views.home, name="home"),
    path("live/", views.live, name="live"),
    path("events/", views.events, name="events"),

    path("video_feed/", views.video_feed, name="video_feed"),

    path("alert_status/", views.alert_status_view, name="alert_status"),
    path("delete_event/<int:id>/", views.delete_event, name="delete_event"),
]