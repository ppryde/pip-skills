DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "fixture11",
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    # pghistory uses Postgres triggers — signals_safe=True, does NOT escalate WRITE-006/007/009
    "pghistory",
    "pgtrigger",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
