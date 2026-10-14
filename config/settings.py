import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me-before-deployment")
DEBUG = os.getenv("DEBUG", "True").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if host.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "routefuel",
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
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache geocoding and routing so identical requests avoid external calls.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "fuel-route-cache"}}
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/hour"},
}

OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
NOMINATIM_BASE_URL = os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org").rstrip("/")
NOMINATIM_USER_AGENT = os.getenv("NOMINATIM_USER_AGENT", "FuelRouteOptimizerAssessment/1.0 (set-a-contact-email)")
FUEL_PRICE_CSV = os.getenv("FUEL_PRICE_CSV", str(BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"))
CENSUS_GAZETTEER_URL = os.getenv("CENSUS_GAZETTEER_URL", "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/2026_Gaz_place_national.zip")
FUEL_ROUTE_CORRIDOR_MILES = float(os.getenv("FUEL_ROUTE_CORRIDOR_MILES", "25"))
FUEL_ROUTE_MAX_RANGE_MILES = float(os.getenv("FUEL_ROUTE_MAX_RANGE_MILES", "500"))
FUEL_ROUTE_MPG = float(os.getenv("FUEL_ROUTE_MPG", "10"))
FUEL_PRICE_CSV_CLEANED = os.getenv("FUEL_PRICE_CSV_CLEANED", str(BASE_DIR / "data" / "processed" / "fuel_prices_cleaned.csv"))
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
