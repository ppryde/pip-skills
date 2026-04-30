DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "fixture07",
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "easyaudit",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
