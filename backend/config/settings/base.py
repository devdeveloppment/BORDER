"""Paramètres communs RBI.

Sûrs par défaut : DEBUG désactivé, secrets obligatoires et lus dans l'environnement.
Modules dérivés : ``development`` (Docker Compose), ``test`` (pytest).
La production est ajoutée avec le déploiement.
"""

from __future__ import annotations

from pathlib import Path

from config.env import env_bool, env_int, env_list, env_str

BASE_DIR = Path(__file__).resolve().parent.parent.parent

RBI_ENV = env_str("RBI_ENV", "production")

SECRET_KEY = env_str("RBI_DJANGO_SECRET_KEY")
DEBUG = env_bool("RBI_DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("RBI_DJANGO_ALLOWED_HOSTS", [])

# --- Applications -------------------------------------------------------------
# Monolithe modulaire (§12.2). Chaque application métier vit dans apps/<nom>, label court identique.
DJANGO_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.gis",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "drf_spectacular",
    "django_otp",
    "django_otp.plugins.otp_totp",
]
RBI_APPS = [
    "apps.core",
    "apps.health",
    "apps.authentication",
    "apps.organizations",
    "apps.users",
    "apps.border_posts",
    "apps.activities",
    "apps.vehicles",
    "apps.events",
    "apps.alerts",
    "apps.analytics",
    "apps.risk_engine",
    "apps.reports",
    "apps.notifications",
    "apps.audit",
    "apps.integrations",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + RBI_APPS

# Modèle utilisateur personnalisé dès la première migration
# (le changer ensuite imposerait de recréer la base).
AUTH_USER_MODEL = "users.User"

# Ordre significatif : contexte de requête (identifiant de corrélation, IP ; P2.7) → session → CSRF →
# identité (revérifiée en base à chaque requête) → politique de session (durée absolue, MFA ; peut fermer la
# session) → périmètre applicatif et PostgreSQL (RLS) → refus par défaut des vues non publiques.
MIDDLEWARE = [
    "apps.core.client_ip.TrustedProxyMiddleware",
    "apps.core.request_context.RequestContextMiddleware",
    "apps.core.http.ApiResponseMiddleware",
    "apps.core.http.RequestSizeLimitMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.authentication.middleware.SessionPolicyMiddleware",
    "apps.organizations.middleware.TenantContextMiddleware",
    "apps.authentication.middleware.AuthenticationRequiredMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

# --- Base de données ------------------------------------------------------------
# Le rôle est fourni par l'environnement du conteneur :
#   - API et Celery : rôle applicatif (non propriétaire, soumis au RLS) ;
#   - migrations et création des bases de test : rôle propriétaire.
# Le contexte d'organisme sera posé par transaction (SET LOCAL, P2.6) :
# compatible avec les connexions persistantes.
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": env_str("RBI_DB_HOST"),
        "PORT": env_int("RBI_DB_PORT", 5432),
        "NAME": env_str("RBI_DB_NAME"),
        "USER": env_str("RBI_DB_USER"),
        "PASSWORD": env_str("RBI_DB_PASSWORD"),
        "CONN_MAX_AGE": env_int("RBI_DB_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "connect_timeout": 5,
            "application_name": env_str("RBI_DB_APPLICATION_NAME", "rbi"),
        },
    }
}

# Clés primaires UUID pour les modèles RBI (§14.2) via apps.core.models ; valeur par défaut pour les tiers.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Redis : cache et Celery ---------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env_str("RBI_CACHE_URL"),
        "KEY_PREFIX": "rbi",
        "TIMEOUT": 300,
    },
    # Base Redis dédiée : vider le cache applicatif ne ferme aucune session.
    "sessions": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env_str("RBI_SESSION_CACHE_URL"),
        "KEY_PREFIX": "rbi-session",
    },
}

CELERY_BROKER_URL = env_str("RBI_CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = env_str("RBI_CELERY_RESULT_BACKEND")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]  # jamais pickle : pas d'exécution de code via le broker
CELERY_RESULT_EXPIRES = 3600
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 15 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 14 * 60
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TIMEZONE = "UTC"

# --- Internationalisation -----------------------------------------------------------
LANGUAGE_CODE = "fr"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Authentification (§19.1, P2.5) ----------------------------------------------------
AUTHENTICATION_BACKENDS = ["apps.authentication.backends.RBIAuthBackend"]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",  # vérification d'anciens hachages uniquement
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    # Liste de ~20 000 mots de passe compromis embarquée par Django (aucun appel à un service externe).
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_RESET_TIMEOUT = 30 * 60  # lien à usage unique valable 30 minutes (écran 8)
OTP_TOTP_ISSUER = "RIZTECH Border Intelligence"
RBI_MFA_PENDING_TTL = 5 * 60  # durée de l'étape intermédiaire « mot de passe vérifié, MFA en attente »
RBI_SESSION_ABSOLUTE_MAX = 12 * 60 * 60
RBI_FRONTEND_URL = env_str("RBI_FRONTEND_URL", "http://localhost:5173")
DEFAULT_FROM_EMAIL = env_str("RBI_DEFAULT_FROM_EMAIL", "RBI <no-reply@rbi.local>")

# --- Sessions et cookies (§19.1) -------------------------------------------------------
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "sessions"
SESSION_COOKIE_NAME = "rbi_session"
SESSION_COOKIE_AGE = 30 * 60  # expiration après 30 minutes d'inactivité…
SESSION_SAVE_EVERY_REQUEST = True  # …renouvelée à chaque requête
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SECURE = not DEBUG
# Le client relit le cookie CSRF pour l'en-tête X-CSRFToken (frontend P1) : il ne peut pas être HttpOnly.
CSRF_COOKIE_HTTPONLY = False
CSRF_FAILURE_VIEW = "apps.core.http.csrf_failure"
CSRF_TRUSTED_ORIGINS = env_list("RBI_CSRF_TRUSTED_ORIGINS", [])

# --- Proxy de confiance et HTTPS (P2.10, ADR 0012)
# ------------------------------------------------------------
# Adresses ou réseaux (au plus /16 en IPv4, /48 en IPv6) des proxys dont X-Forwarded-For et X-Forwarded-Proto
# sont
# crus ; vide = aucun : adresse du pair TCP, en-têtes de transfert supprimés (apps.core.client_ip).
RBI_TRUSTED_PROXIES = env_list("RBI_TRUSTED_PROXIES", [])
# HTTPS terminé par le proxy : X-Forwarded-Proto n'est conservé que s'il vient d'un proxy déclaré.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if RBI_TRUSTED_PROXIES else None
USE_X_FORWARDED_HOST = False
# HSTS et redirection HTTP → HTTPS : posés par Nginx sur les seules réponses HTTPS (infra/nginx).

# --- Row-Level Security (P2.6) -----------------------------------------------------------------
# Rôle applicatif soumis au RLS, nommé dans les migrations (privilèges) et les contrôles de rôle.
RBI_DB_APP_ROLE = env_str("RBI_DB_APP_USER", "rbi_app")

# --- API REST v1 (P2.8, ADR 0010) ---------------------------------------------------------------------
# Refus par défaut : chaque vue déclare sa politique (apps/core/api/views.py) ; session uniquement (P2.5),
# JSON uniquement, erreurs RFC 9457, limitation de débit par compte et par adresse (§15.1).
RBI_API_MAX_BODY_BYTES = 64 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = RBI_API_MAX_BODY_BYTES
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.core.api.policy.RBISessionAuthentication"],
    # Vue sans politique déclarée : RBIPolicy refuse (aucun raccourci is_staff / is_superuser).
    "DEFAULT_PERMISSION_CLASSES": ["apps.core.api.policy.RBIPolicy"],
    "DEFAULT_PARSER_CLASSES": ["apps.core.api.policy.BoundedJSONParser"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "EXCEPTION_HANDLER": "apps.core.api.errors.problem_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "apps.core.api.schema.RBIAutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.core.api.throttling.UserRateThrottle",
        "apps.core.api.throttling.AnonRateThrottle",
    ],
    # audit_heavy : export et vérification d'intégrité (coût proportionnel au journal), par compte.
    "DEFAULT_THROTTLE_RATES": {
        "user": "600/min",
        "anon": "120/min",
        "access_request": "5/hour",
        "audit_heavy": "10/min",
    },
    # Défense en profondeur : les classes RBI ci-dessus lisent l'adresse de la politique du proxy
    # de confiance (apps.core.client_ip, P2.10) ; NUM_PROXIES=0 empêche DRF d'en lire une autre.
    "NUM_PROXIES": 0,
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "RIZTECH Border Intelligence — API v1",
    "DESCRIPTION": (
        "API REST de RBI (données fictives de démonstration uniquement). Session HttpOnly + CSRF, MFA "
        "selon le rôle, permissions RBAC évaluées côté serveur, isolation par organisme (RLS PostgreSQL). "
        "Erreurs au format RFC 9457 ; un objet d'un autre organisme renvoie 404."
    ),
    "VERSION": "1.0.0",
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {"OrganizationRoleEnum": "apps.users.api.ORGANIZATION_ROLES"},
    "SERVERS": [{"url": "/", "description": "Même origine que l'application web"}],
}

# --- Journal d'audit (P2.7, ADR 0009) ------------------------------------------------------------------
# « autonomous » : connexion d'écriture dédiée, refus et échecs conservés même si la transaction métier est
# annulée. « inline » est réservé aux tests (contrôle système rbi.E001).
RBI_AUDIT_WRITE_MODE = "autonomous"
# §9.11 : adresse IP « si juridiquement et techniquement approprié ». Activée sur données fictives ; à
# confirmer par l'analyse juridique de chaque organisme avant tout traitement de données réelles.
RBI_AUDIT_RECORD_IP = env_bool("RBI_AUDIT_RECORD_IP", True)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# --- Journalisation -----------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env_str("RBI_LOG_LEVEL", "INFO")},
}
