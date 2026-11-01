"""
auth.py - Authentication, password hashing, and role-based access control for Smart Attendance System.
Uses werkzeug.security for cryptographic PBKDF2/SHA256 password hashing.
Provides route decorators for session verification and role enforcement.
"""

from functools import wraps
from typing import Optional, Dict, Any, Tuple
from flask import session, request, redirect, url_for, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_cursor
import config


class AuthService:
    @staticmethod
    def create_user(username: str, password: str, role: str, db_path=None) -> Optional[Dict[str, Any]]:
        """
        Creates a new user with a hashed password.
        Valid roles: 'admin', 'faculty', 'student'
        """
        if role not in ('admin', 'faculty', 'student'):
            raise ValueError(f"Invalid role: {role}. Must be 'admin', 'faculty', or 'student'.")

        password_hash = generate_password_hash(password)
        try:
            with get_db_cursor(db_path) as cursor:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?);",
                    (username.strip().lower(), password_hash, role)
                )
                user_id = cursor.lastrowid
                cursor.execute("SELECT id, username, role, created_at FROM users WHERE id = ?;", (user_id,))
                return dict(cursor.fetchone())
        except Exception:
            return None

    @staticmethod
    def authenticate(username: str, password: str, db_path=None) -> Optional[Dict[str, Any]]:
        """
        Authenticates a user by username and password.
        Verifies cryptographic password hashes and transparently upgrades legacy plaintext seeds.
        Returns user dictionary (without password_hash) if valid, else None.
        """
        if not username or not password:
            return None

        # In production mode, block use of known default development passwords
        KNOWN_DEV_PASSWORDS = {'faculty123', 'admin123', 'password', 'changeme', '123456'}
        if getattr(config.Config, 'IS_PRODUCTION', False) and password in KNOWN_DEV_PASSWORDS:
            return None

        clean_username = username.strip().lower()

        with get_db_cursor(db_path, commit=True) as cursor:
            cursor.execute(
                "SELECT id, username, password_hash, role, created_at FROM users WHERE username = ?;",
                (clean_username,)
            )
            row = cursor.fetchone()
            if not row:
                return None

            user_data = dict(row)
            stored_hash = user_data['password_hash']
            authenticated = False

            # Check if stored_hash is a standard Werkzeug hash
            if stored_hash.startswith(('scrypt:', 'pbkdf2:')):
                if check_password_hash(stored_hash, password):
                    authenticated = True
            elif stored_hash == password:
                # Transparent upgrade for legacy unhashed development/seed records
                new_hash = generate_password_hash(password)
                cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?;", (new_hash, user_data['id']))
                authenticated = True

            if not authenticated:
                return None

            # Never expose the password hash
            del user_data['password_hash']

            # Enrich user data with Faculty metadata if applicable
            if user_data['role'] == 'faculty':
                cursor.execute("SELECT faculty_id, name, email FROM faculty WHERE user_id = ?;", (user_data['id'],))
                fac = cursor.fetchone()
                if fac:
                    user_data['faculty_id'] = fac['faculty_id']
                    user_data['name'] = fac['name']
                    user_data['email'] = fac['email']
                else:
                    user_data['name'] = user_data['username']
            elif user_data['role'] == 'admin':
                user_data['name'] = 'Administrator'
            else:
                user_data['name'] = user_data['username']

            return user_data

    @staticmethod
    def get_user_by_id(user_id: int, db_path=None) -> Optional[Dict[str, Any]]:
        """Fetches user profile by ID without exposing password hash."""
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                "SELECT id, username, role, created_at FROM users WHERE id = ?;",
                (user_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def has_role(user: Dict[str, Any], *required_roles: str) -> bool:
        """Checks whether the user holds one of the required roles or is an administrator."""
        if not user or 'role' not in user:
            return False
        user_role = str(user.get('role', '')).lower()
        target_roles = [r.lower() for r in required_roles]
        return user_role == 'admin' or user_role in target_roles


def is_api_request() -> bool:
    """Helper to determine whether the incoming request expects a JSON API response."""
    return (
        request.path.startswith('/api/') or
        request.is_json or
        request.headers.get('Accept', '').find('application/json') != -1
    )


def login_required(f):
    """Requires an authenticated session user."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user')
        if not user:
            if is_api_request():
                return jsonify({
                    'status': 'error',
                    'error': 'Unauthorized',
                    'message': 'Authentication required to access this resource.'
                }), 401
            flash('Please log in with faculty credentials to access this portal.', 'warning')
            return redirect(url_for('frontend.login'))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*required_roles: str):
    """Enforces specific user role(s). Admin automatically satisfies all roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = session.get('user')
            if not user:
                if is_api_request():
                    return jsonify({
                        'status': 'error',
                        'error': 'Unauthorized',
                        'message': 'Authentication required to access this resource.'
                    }), 401
                flash('Please log in with faculty credentials to access this portal.', 'warning')
                return redirect(url_for('frontend.login'))

            if not AuthService.has_role(user, *required_roles):
                if is_api_request():
                    return jsonify({
                        'status': 'error',
                        'error': 'Forbidden',
                        'message': f"Access denied: this operation requires {', '.join(required_roles)} privileges."
                    }), 403
                flash('Access denied: You do not have permission to access this resource.', 'danger')
                return ("Access denied: Requires " + ", ".join(required_roles) + " role.", 403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def faculty_required(f):
    """Enforces faculty or administrator authorization."""
    return role_required('faculty', 'admin')(f)


def admin_required(f):
    """Enforces administrator authorization."""
    return role_required('admin')(f)
