import os

from django.core.wsgi import get_wsgi_application

# Par défaut, réglages sûrs (DEBUG désactivé) ; développement et tests nomment leur module.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

application = get_wsgi_application()
