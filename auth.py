"""
auth.py - Authentication, password hashing, and role-based access control for Smart Attendance System.
Uses werkzeug.security for industry-standard PBKDF2/SHA256 password hashing.
"""

from typing import Optional, Dict, Any
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_cursor


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
        Authenticates a user by username and plaintext password.
        Returns user dictionary (without password_hash) if valid, else None.
        """
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                "SELECT id, username, password_hash, role, created_at FROM users WHERE username = ?;",
                (username.strip().lower(),)
            )
            row = cursor.fetchone()
            if not row:
                return None

            user_data = dict(row)
            if check_password_hash(user_data['password_hash'], password):
                del user_data['password_hash']
                return user_data
            return None

    @staticmethod
    def get_user_by_id(user_id: int, db_path=None) -> Optional[Dict[str, Any]]:
        """
        Fetches user profile by ID without exposing password hash.
        """
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                "SELECT id, username, role, created_at FROM users WHERE id = ?;",
                (user_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def has_role(user: Dict[str, Any], required_role: str) -> bool:
        """
        Checks whether the user holds the required role or is an admin.
        """
        if not user or 'role' not in user:
            return False
        return user['role'] == required_role or user['role'] == 'admin'
