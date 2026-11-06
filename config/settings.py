"""
Django settings for the Willow Cross HMS project.
"""
import os
import sys
import pymysql
from pathlib import Path
from decouple import config, Csv
from django.core.exceptions import ImproperlyConfigured

pymysql.install_as_MySQLdb()  # lets Django's mysql backend run on the pure-Python driver

BASE_DIR = Path(__file__).resolve().parent.parent

# True when running on Vercel (it sets VERCEL=1 in builds and functions).
ON_VERCEL = bool(os.environ.get('VERCEL'))

_PLACEHOLDER_KEYS = {'django-insecure-change-me-in-production', 'change-me-to-a-random-secret-key'}
SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-me-in-production')

# Off unless explicitly turned on. .env.example sets DEBUG=True for local
# development; a deployment that forgets to configure anything stays safe.
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())

if ON_VERCEL:
    # *.vercel.app covers the production and preview URLs Vercel generates.
    # Add your custom domain via ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS env vars.
    ALLOWED_HOSTS = list(ALLOWED_HOSTS) + ['.vercel.app']
    CSRF_TRUSTED_ORIGINS = list(CSRF_TRUSTED_ORIGINS) + ['https://*.vercel.app']

if not DEBUG and SECRET_KEY in _PLACEHOLDER_KEYS and 'test' not in sys.argv:
    raise ImproperlyConfigured(
        "SECRET_KEY is still a placeholder while DEBUG is off. Copy .env.example to .env "
        "(which sets DEBUG=True for local work), or set a real SECRET_KEY."
    )

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    # Willow Cross HMS — Phase 1 modules
    'accounts',
    'patients',
    'ehr',
    'appointments',
    'opd',
    'ipd',
    'pharmacy',
    'laboratory',
    'billing',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # serves /static/ (Vercel has no web server for it)
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.ui_permissions',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# --- Database -----------------------------------------------------------
# MySQL on PyMySQL. Vercel's filesystem is read-only/ephemeral, so SQLite cannot
# be used there: set DATABASE_URL to your hosted MySQL (e.g. Aiven's "Service URI",
#   mysql://avnadmin:PASSWORD@HOST:PORT/defaultdb?ssl-mode=REQUIRED
# ). Without DATABASE_URL the individual DB_* variables are used, and
# DB_ENGINE=sqlite still gives a zero-setup local run.
_DATABASE_URL = config('DATABASE_URL', default='')
if _DATABASE_URL:
    import dj_database_url
    # Drop the "?ssl-mode=REQUIRED" style query string: dj-database-url would pass
    # it to PyMySQL as an unknown option and crash. TLS is configured below.
    DATABASES = {'default': dj_database_url.parse(_DATABASE_URL.split('?', 1)[0], conn_max_age=0)}
    DATABASES['default']['ENGINE'] = 'django.db.backends.mysql'
    DATABASES['default'].setdefault('OPTIONS', {})['charset'] = 'utf8mb4'
elif config('DB_ENGINE', default='mysql') == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': config('DB_NAME', default='willow_cross_hms'),
            'USER': config('DB_USER', default='root'),
            'PASSWORD': config('DB_PASSWORD', default=''),
            'HOST': config('DB_HOST', default='127.0.0.1'),
            'PORT': config('DB_PORT', default='3306'),
            'OPTIONS': {'charset': 'utf8mb4'},
        }
    }

# TLS to hosted MySQL (Aiven requires it, and signs with its own project CA, so
# the public CA bundle is NOT enough). Provide Aiven's CA certificate one of three ways:
#   1. DB_SSL_CA_PEM  - the full contents of ca.pem as an environment variable (Vercel)
#   2. DB_SSL_CA      - a path to a CA file
#   3. a file at certs/ca.pem in this project (the CA certificate is public, safe to commit)
# DB_SSL=True with none of those falls back to the certifi public bundle.
# The certificate text is cleaned and re-wrapped first, so pasting it with lost line
# breaks, extra spaces, quotes or literal \n sequences still works.
if DATABASES['default']['ENGINE'].endswith('mysql'):
    import re
    import tempfile
    _pem = config('DB_SSL_CA_PEM', default='')
    _ca_file = config('DB_SSL_CA', default='')
    if not _pem and not _ca_file and (BASE_DIR / 'certs' / 'ca.pem').exists():
        _ca_file = str(BASE_DIR / 'certs' / 'ca.pem')
    if not _pem and _ca_file:
        with open(_ca_file) as _f:
            _pem = _f.read()
    _ca = ''
    if _pem.strip():
        _blocks = re.findall(r'-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----',
                             _pem.replace('\\n', '\n'), re.S)
        if not _blocks:
            raise ImproperlyConfigured(
                'The database CA certificate (DB_SSL_CA_PEM or certs/ca.pem) has no '
                '"-----BEGIN CERTIFICATE-----" ... "-----END CERTIFICATE-----" block. '
                "Paste the full contents of Aiven's ca.pem.")
        _clean = ''
        for _b in _blocks:
            _b = re.sub(r'[^A-Za-z0-9+/=]', '', _b)
            _clean += ('-----BEGIN CERTIFICATE-----\n'
                       + '\n'.join(_b[i:i + 64] for i in range(0, len(_b), 64))
                       + '\n-----END CERTIFICATE-----\n')
        _ca = os.path.join(tempfile.gettempdir(), 'db-ca.pem')
        with open(_ca, 'w') as _f:
            _f.write(_clean)
    elif config('DB_SSL', default=False, cast=bool):
        import certifi
        _ca = certifi.where()
    if _ca:
        DATABASES['default']['OPTIONS']['ssl'] = {'ca': _ca}

AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'core:dashboard'
LOGOUT_REDIRECT_URL = 'accounts:login'

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lagos'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Serve static files straight from the app/static finders (including the admin's),
# so nothing has to run `collectstatic` at build time on Vercel.
WHITENOISE_USE_FINDERS = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Shown on printed invoices and in the admin header. Set these in .env.
HOSPITAL_NAME = config('HOSPITAL_NAME', default='Willow Cross Hospital')
HOSPITAL_ADDRESS = config('HOSPITAL_ADDRESS', default='')
HOSPITAL_PHONE = config('HOSPITAL_PHONE', default='')

# Tests create many users; the default PBKDF2 hasher is deliberately slow and
# made the suite take over a minute. Fast hashing is fine for throwaway data.
if 'test' in sys.argv:
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# --- Production hardening (only when DEBUG is off) ---------------------------
# Serve the site over HTTPS only. Set SECURE_SSL_REDIRECT=False if TLS is
# terminated somewhere that can't set the proxy header, and raise
# SECURE_HSTS_SECONDS (e.g. 31536000) once you've confirmed HTTPS works.
if not DEBUG and 'test' not in sys.argv:
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=3600, cast=int)
    if config('BEHIND_PROXY', default=ON_VERCEL, cast=bool):
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
