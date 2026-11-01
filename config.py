"""
config.py - Application configuration and environment-variable security management
for Smart Attendance System.
Enforces secure secrets, production safeguards, CSRF protection, and session cookie policies.
"""

import os
from datetime import timedelta

KNOWN_INSECURE_SECRETS = {
    'dev-insecure-secret-key-change-in-production',
    'smart-attendance-dev-secret-key-2026',
    'test-secret-key',
    'secret',
    'default',
    'changeme',
    'password',
    '123456'
}


class Config:
    """Centralized configuration loaded from environment variables."""

    # Environment detection
    ENV = os.environ.get('FLASK_ENV', os.environ.get('ENV', 'development')).lower()
    IS_PRODUCTION = ENV in ('production', 'prod')

    # Flask Session Secret Key
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if IS_PRODUCTION:
        if not SECRET_KEY or SECRET_KEY in KNOWN_INSECURE_SECRETS:
            raise RuntimeError(
                "CRITICAL SECURITY CONFIGURATION ERROR: "
                "A secure, non-default SECRET_KEY environment variable must be explicitly configured in production mode. "
                "Application startup aborted."
            )
    else:
        # Development / Testing fallback with distinct non-production value
        if not SECRET_KEY:
            SECRET_KEY = 'dev-insecure-secret-key-change-in-production'

    # Security Cookies & Session Settings
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    # In production, require HTTPS for session cookies unless explicitly disabled
    SESSION_COOKIE_SECURE = (
        os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() in ('true', '1')
        if IS_PRODUCTION
        else os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() in ('true', '1')
    )
    PERMANENT_SESSION_LIFETIME = timedelta(
        seconds=int(os.environ.get('PERMANENT_SESSION_LIFETIME', 3600))
    )

    # CSRF Protection Settings (Flask-WTF)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = int(os.environ.get('WTF_CSRF_TIME_LIMIT', 3600))  # 1 hour
    WTF_CSRF_CHECK_DEFAULT = True

    # Database Path (Optional override)
    DB_PATH = os.environ.get('DB_PATH')

    # Camera / Kiosk API Key (strictly scoped to automated hardware camera frame submission)
    CAMERA_API_KEY = os.environ.get('CAMERA_API_KEY')

    # Debug mode - strictly disabled in production
    DEBUG = False if IS_PRODUCTION else os.environ.get('FLASK_DEBUG', 'false').lower() in ('true', '1')
