import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "thisisnotasecretkey")
DEBUG = os.environ.get("DEBUG", "true").lower() != "false"

# Internal docker-compose hostname(s) other services use to reach web over the
# compose network (e.g. the MCP server and vm_service call http://web:8000/api/v1).
# Always trusted so service-to-service traffic never hits DisallowedHost, regardless
# of the public ALLOWED_HOSTS configured for prod (which usually only lists the
# external domain). Override INTERNAL_HOSTS if the web service is renamed.
INTERNAL_HOSTS = [
    h.strip()
    for h in os.environ.get("INTERNAL_HOSTS", "web,localhost,127.0.0.1").split(",")
    if h.strip()
]

ALLOWED_HOSTS = INTERNAL_HOSTS + [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "").split(",")
    if h.strip() and h.strip() not in INTERNAL_HOSTS
]

# External port the app is reached on (the nginx host mapping). Browsers omit the
# port for 80/443, so CSRF origins must match with AND without an explicit port.
HTTP_PORT = os.environ.get("HTTP_PORT", "80").strip()
_csrf_ports = [""]
if HTTP_PORT and HTTP_PORT not in ("80", "443"):
    _csrf_ports.append(f":{HTTP_PORT}")
CSRF_TRUSTED_ORIGINS = [
    f"{scheme}://{h}{port}"
    for h in ALLOWED_HOSTS
    for port in _csrf_ports
    for scheme in ("http", "https")
]

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/1")
REDIS_PORT = int(REDIS_URL.split(":")[-1].split("/")[0])
REDIS_HOST = REDIS_URL.split(":")[1].split("/")[-1]

REDIS_PREFIX = os.getenv("REDIS_PREFIX", "web_service:")

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "channels",
    "drf_spectacular",
    "internal_config",
    "vm_manager",
    "ai_services",
    "platform_api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "pequeroku.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "pequeroku.wsgi.application"

REST_FRAMEWORK = {
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Pequeroku",
    "DESCRIPTION": "Easy way to share a piece of your machine...",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Keep the public /api/v1 surface out of the IDE schema; it ships its own
    # schema at /api/v1/schema/ (see platform_api.schema).
    "PREPROCESSING_HOOKS": ["platform_api.schema.exclude_v1_from_default"],
}

# Django cache: Redis in prod (shared across gunicorn workers, so Idempotency-Key
# and per-key throttling are consistent). Tests override this with locmem.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# Per-API-key rate limit for the public surface (overridable by ops).
PLATFORM_API_THROTTLE_RATE = os.getenv("PLATFORM_API_THROTTLE_RATE", "120/min")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [(REDIS_HOST, REDIS_PORT)],
        },
    },
}

ASGI_APPLICATION = "pequeroku.asgi.application"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME"),
        "USER": os.environ.get("DB_USER"),
        "PASSWORD": os.environ.get("DB_PASSWORD"),
        "HOST": os.environ.get("DB_HOST"),
        "PORT": os.environ.get("DB_PORT"),
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATIC_URL = "static/"

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media/")

# Logging: single console handler (stdout) so output is captured by the container
# runtime / gunicorn. Level is overridable per deploy via LOG_LEVEL; our own apps
# default to that level while noisy third-party loggers stay at WARNING.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        app: {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        }
        for app in ("vm_manager", "ai_services", "internal_config", "platform_api")
    },
}
