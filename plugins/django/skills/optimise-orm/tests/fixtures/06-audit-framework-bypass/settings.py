DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "fixture06",
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    # easyaudit (django-easy-audit) present — triggers WRITE-006/007/009 escalation to critical
    "easyaudit",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
