DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "fixture12",
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django version context for the skill
DJANGO_VERSION = (4, 2, 0)
