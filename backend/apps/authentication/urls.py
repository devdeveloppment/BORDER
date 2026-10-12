from django.urls import path

from . import views

app_name = "authentication"

urlpatterns = [
    path("csrf", views.CsrfView.as_view(), name="csrf"),
    path("login", views.LoginView.as_view(), name="login"),
    path("mfa/enroll", views.MfaEnrollView.as_view(), name="mfa-enroll"),
    path("mfa/verify", views.MfaVerifyView.as_view(), name="mfa-verify"),
    path("logout", views.LogoutView.as_view(), name="logout"),
    path("password-reset", views.PasswordResetView.as_view(), name="password-reset"),
    path("password-reset/confirm", views.PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
    path("password/change", views.PasswordChangeView.as_view(), name="password-change"),
    path("sessions/revoke-others", views.SessionsRevokeOthersView.as_view(), name="sessions-revoke-others"),
    path("mfa/totp/renew", views.MfaTotpRenewView.as_view(), name="mfa-totp-renew"),
    path("mfa/totp/renew/confirm", views.MfaTotpRenewConfirmView.as_view(), name="mfa-totp-renew-confirm"),
    path("mfa/backup-codes", views.MfaBackupCodesView.as_view(), name="mfa-backup-codes"),
    path("mfa/disable", views.MfaDisableView.as_view(), name="mfa-disable"),
]
