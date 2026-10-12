"""Développement local sous Docker Compose."""

from __future__ import annotations

from config.env import env_bool, env_int, env_list

from .base import *  # noqa: F403
from .base import DATABASES

RBI_ENV = "development"
# Le serveur de développement crée un thread par requête : une connexion persistante par thread
# s'accumulerait jusqu'à épuiser max_connections. Connexions persistantes réservées au serveur WSGI.
DATABASES["default"]["CONN_MAX_AGE"] = env_int("RBI_DB_CONN_MAX_AGE", 0)
DEBUG = env_bool("RBI_DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("RBI_DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])
# HTTP en local (Nginx sur 127.0.0.1:8080) ; RBI_HTTPS=true lorsque Nginx termine TLS (P2.10, ADR 0012).
RBI_HTTPS = env_bool("RBI_HTTPS", False)
SESSION_COOKIE_SECURE = RBI_HTTPS
CSRF_COOKIE_SECURE = RBI_HTTPS

# Capture des e-mails par Mailpit (ADR 0001 · P12) : aucun SMTP réel.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "mailpit"
EMAIL_PORT = 1025
