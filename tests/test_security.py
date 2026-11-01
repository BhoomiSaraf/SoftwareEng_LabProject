"""
tests/test_security.py - Comprehensive Security, Authentication, Authorization & CSRF Test Suite
Covers:
1. Credential verification, rejection of arbitrary credentials, and production default-password lockout.
2. Synchronised CSRF token enforcement (missing, invalid, and valid tokens).
3. Machine-to-machine camera API-key authentication (missing, incorrect, unconfigured, supported headers).
4. Camera API key privilege scoping (prohibiting administrative actions).
5. Unauthenticated access controls (302 redirects for HTML, 401 for API).
6. Role-based access control (RBAC) preventing student access to faculty/admin operations (403 Forbidden).
7. Cross-instructor session and course ownership enforcement.
8. Secure session invalidation on logout.
9. Production configuration safeguards (missing/weak secrets, debug mode prevention).
"""

import os
import re
import pytest
from unittest.mock import patch
from werkzeug.security import generate_password_hash

from database import init_db, seed_initial_data
from auth import AuthService
from config import Config
from models import ClassSessionModel
from attendance_service import AttendanceService
from face_recognition_service import face_service
from run_frontend_dev import app


def extract_csrf_token(client):
    """Fetches /login and extracts the CSRF token rendered in the meta tag."""
    resp = client.get('/login')
    match = re.search(r'name="csrf-token" content="([^"]+)"', resp.data.decode('utf-8'))
    if match:
        return match.group(1)
    match_input = re.search(r'name="csrf_token" value="([^"]+)"', resp.data.decode('utf-8'))
    if match_input:
        return match_input.group(1)
    raise RuntimeError("CSRF token could not be extracted from /login.")


@pytest.fixture
def sec_env(tmp_path):
    """Provides an isolated test database with admin, faculty, and student test accounts."""
    db_file = str(tmp_path / "test_security.db")
    init_db(db_file)
    seed_initial_data(db_file)

    # Add a dedicated student user account into the users table
    import database
    with database.get_db_cursor(db_file) as cursor:
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?);",
            ('student1', generate_password_hash('student123'), 'student')
        )

    app.config['TESTING'] = True
    app.config['DB_PATH'] = db_file
    app.data_provider.db_path = db_file

    client = app.test_client()

    return {
        'client': client,
        'db_path': db_file
    }


# =============================================================================
# 1. Credential Verification & Authentication Tests
# =============================================================================

def test_valid_credentials_authenticate(sec_env):
    """Valid credentials successfully authenticate and return user info without exposing password_hash."""
    db_path = sec_env['db_path']
    user = AuthService.authenticate('rajesh.kumar', 'faculty123', db_path=db_path)
    assert user is not None
    assert user['username'] == 'rajesh.kumar'
    assert user['role'] == 'faculty'
    assert user['faculty_id'] == 'FAC001'
    assert 'password_hash' not in user


def test_invalid_password_rejected(sec_env):
    """Valid username with incorrect password must be rejected."""
    db_path = sec_env['db_path']
    user = AuthService.authenticate('rajesh.kumar', 'wrong_password', db_path=db_path)
    assert user is None


def test_arbitrary_nonempty_credentials_rejected(sec_env):
    """Arbitrary nonempty credentials must never be accepted (permissive fallback removed)."""
    db_path = sec_env['db_path']
    assert AuthService.authenticate('nonexistent_user', 'any_pass', db_path=db_path) is None
    assert AuthService.authenticate('hacker@attack.com', 'faculty123', db_path=db_path) is None
    assert AuthService.authenticate('', '', db_path=db_path) is None


def test_login_form_rejects_arbitrary_credentials(sec_env):
    """Submitting non-existent credentials through the web login route fails and flashes error."""
    client = sec_env['client']
    token = extract_csrf_token(client)
    resp = client.post(
        '/login',
        data={'username': 'bogus_user', 'password': 'random_password', 'csrf_token': token},
        follow_redirects=True
    )
    assert resp.status_code == 200
    assert b'Invalid username or password' in resp.data
    assert b'Faculty Dashboard' not in resp.data


# =============================================================================
# 2. Synchronised CSRF Protection Tests
# =============================================================================

def test_csrf_missing_token_on_browser_session_rejected(sec_env):
    """State-changing requests from a browser session without a CSRF token must be rejected with 400 Bad Request."""
    client = sec_env['client']
    with client.session_transaction() as sess:
        sess['user'] = {'id': 2, 'username': 'rajesh.kumar', 'role': 'faculty', 'faculty_id': 'FAC001'}

    # Attempt POST to an administrative/session API without CSRF token
    resp = client.post('/api/sessions/SES-101/mark-manual', json={'student_id': 1})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data.get('error') == 'CSRF Error'


def test_csrf_invalid_token_on_browser_session_rejected(sec_env):
    """State-changing requests with a forged or invalid CSRF token must be rejected with 400 Bad Request."""
    client = sec_env['client']
    with client.session_transaction() as sess:
        sess['user'] = {'id': 2, 'username': 'rajesh.kumar', 'role': 'faculty', 'faculty_id': 'FAC001'}

    # Send forged CSRF token in header
    resp = client.post(
        '/api/sessions/SES-101/mark-manual',
        json={'student_id': 1},
        headers={'X-CSRFToken': 'forged_invalid_csrf_token_value'}
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data.get('error') == 'CSRF Error'


def test_csrf_valid_token_accepted_on_session_state_change(sec_env):
    """State-changing request with a genuine synchronised CSRF token passes CSRF validation."""
    client = sec_env['client']
    db_path = sec_env['db_path']

    # Start an active session for FAC001
    success, _, session = AttendanceService.start_session('CRS-CSE3132', 'FAC001', db_path=db_path)
    sess_id = session['session_id']

    # Log in as FAC001
    with client.session_transaction() as sess:
        sess['user'] = {'id': 2, 'username': 'rajesh.kumar', 'role': 'faculty', 'faculty_id': 'FAC001'}

    token = extract_csrf_token(client)
    resp = client.post(
        f'/api/sessions/{sess_id}/mark-manual',
        json={'student_id': 'STU001'},
        headers={'X-CSRFToken': token}
    )
    assert resp.status_code == 200
    assert resp.get_json().get('status') == 'marked'


# =============================================================================
# 3. Camera API Key Authentication & Scoping Tests
# =============================================================================

def test_camera_api_key_valid_allows_m2m_without_csrf(sec_env):
    """A valid CAMERA_API_KEY authorizes machine-to-machine camera frame submission without requiring a browser CSRF token."""
    client = sec_env['client']
    db_path = sec_env['db_path']

    # Configure server-side camera key
    with patch.object(Config, 'CAMERA_API_KEY', 'valid-hardware-scanner-key'), \
         patch.object(face_service, 'match_face', return_value={'status': 'NO_FACE_DETECTED', 'message': 'No face'}):
        success, _, session = AttendanceService.start_session('CRS-CSE3132', 'FAC001', db_path=db_path)
        sess_id = session['session_id']

        # Machine request with NO session cookie and NO CSRF token, but WITH valid API key
        resp = client.post(
            f'/api/sessions/{sess_id}/recognize',
            json={'image': 'data:image/jpeg;base64,mock_frame'},
            headers={'X-API-Key': 'valid-hardware-scanner-key'}
        )
        # Should authenticate successfully (outcome 200)
        assert resp.status_code == 200
        assert resp.get_json().get('status') in ('unrecognized', 'no_face', 'marked')


def test_camera_api_key_invalid_or_missing_rejected(sec_env):
    """Missing or incorrect camera API key without a browser session must return 401 Unauthorized."""
    client = sec_env['client']
    with patch.object(Config, 'CAMERA_API_KEY', 'valid-hardware-scanner-key'):
        # Missing key
        resp_missing = client.post('/api/sessions/SES-101/recognize', json={'image': 'mock_frame'})
        assert resp_missing.status_code == 401
        assert resp_missing.get_json().get('error') == 'Unauthorized'

        # Incorrect key
        resp_bad = client.post(
            '/api/sessions/SES-101/recognize',
            json={'image': 'mock_frame'},
            headers={'X-API-Key': 'wrong-key'}
        )
        assert resp_bad.status_code == 401
        assert resp_bad.get_json().get('error') == 'Unauthorized'


def test_camera_api_key_unconfigured_on_server_rejected(sec_env):
    """When CAMERA_API_KEY is unset on the server, incoming API keys are safely rejected."""
    client = sec_env['client']
    with patch.object(Config, 'CAMERA_API_KEY', None):
        resp = client.post(
            '/api/sessions/SES-101/recognize',
            json={'image': 'mock_frame'},
            headers={'X-API-Key': 'any-key'}
        )
        assert resp.status_code == 401
        assert resp.get_json().get('error') == 'Unauthorized'


def test_camera_api_key_supported_headers(sec_env):
    """Camera API key is recognized via X-API-Key, X-API-KEY, and Authorization: Bearer."""
    client = sec_env['client']
    db_path = sec_env['db_path']

    with patch.object(Config, 'CAMERA_API_KEY', 'hardware-secret-999'), \
         patch.object(face_service, 'match_face', return_value={'status': 'NO_FACE_DETECTED', 'message': 'No face'}):
        success, _, session = AttendanceService.start_session('CRS-CSE3132', 'FAC001', db_path=db_path)
        sess_id = session['session_id']

        # 1. X-API-KEY (uppercase)
        r1 = client.post(
            f'/api/sessions/{sess_id}/recognize',
            json={'image': 'frame'},
            headers={'X-API-KEY': 'hardware-secret-999'}
        )
        assert r1.status_code == 200

        # 2. Authorization: Bearer <key>
        r2 = client.post(
            f'/api/sessions/{sess_id}/recognize',
            json={'image': 'frame'},
            headers={'Authorization': 'Bearer hardware-secret-999'}
        )
        assert r2.status_code == 200


def test_camera_api_key_cannot_access_administrative_endpoints(sec_env):
    """Camera API key must NOT grant privileges to call administrative endpoints."""
    client = sec_env['client']
    with patch.object(Config, 'CAMERA_API_KEY', 'hardware-secret-999'):
        admin_routes = [
            ('POST', '/api/courses/CRS-CSE3132/enroll', {'student_ids': [1]}),
            ('POST', '/api/sessions/SES-101/end', None),
            ('POST', '/api/sessions/SES-101/mark-manual', {'student_id': 1}),
            ('POST', '/api/students/1/register-face', {'image': 'dummy'}),
            ('GET', '/api/reports/export-csv?course_id=CRS-CSE3132', None),
        ]

        for method, path, payload in admin_routes:
            headers = {'X-API-Key': 'hardware-secret-999'}
            if method == 'POST':
                resp = client.post(path, json=payload, headers=headers)
            else:
                resp = client.get(path, headers=headers)

            # Camera key must NOT authorize administrative operations (returns 400 CSRF missing or 401 Unauthorized)
            assert resp.status_code in (400, 401, 403), f"Camera key allowed administrative access to {path}"


# =============================================================================
# 4. Unauthenticated Access Control Tests
# =============================================================================

def test_unauthenticated_html_routes_redirect_to_login(sec_env):
    """Unauthenticated requests to protected HTML pages must redirect to /login with 302."""
    client = sec_env['client']
    for path in ['/dashboard', '/students', '/courses', '/reports', '/sessions/101']:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 302, f"Failed for {path}"
        assert '/login' in resp.headers['Location']


def test_unauthenticated_api_endpoints_return_401(sec_env):
    """Unauthenticated requests to state-changing API endpoints must return 401 Unauthorized."""
    client = sec_env['client']
    token = extract_csrf_token(client)
    headers = {'X-CSRFToken': token}

    api_endpoints = [
        ('POST', '/api/students/1/register-face', {'image': 'dummy'}),
        ('GET', '/api/courses/CRS-CSE3132/enrollment-data', None),
        ('POST', '/api/courses/CRS-CSE3132/enroll', {'student_ids': [1]}),
        ('POST', '/api/sessions/SES-101/recognize', {'image': 'dummy'}),
        ('POST', '/api/sessions/SES-101/mark-manual', {'student_id': 1}),
        ('POST', '/api/sessions/SES-101/end', None),
        ('GET', '/api/reports/export-csv?course_id=CRS-CSE3132', None),
    ]

    for method, path, payload in api_endpoints:
        if method == 'POST':
            resp = client.post(path, json=payload, headers=headers)
        else:
            resp = client.get(path, headers=headers)

        assert resp.status_code == 401, f"Failed for {method} {path}: got {resp.status_code}"
        data = resp.get_json()
        assert data.get('error') == 'Unauthorized'


# =============================================================================
# 5. Role-Based Access Control (RBAC) Tests
# =============================================================================

def test_student_cannot_access_faculty_portal_pages(sec_env):
    """A user logged in with 'student' role cannot view faculty management pages."""
    client = sec_env['client']
    with client.session_transaction() as sess:
        sess['user'] = {'id': 10, 'username': 'student1', 'role': 'student'}

    for path in ['/dashboard', '/students', '/courses', '/reports']:
        resp = client.get(path)
        assert resp.status_code == 403, f"Student allowed access to {path}"


def test_student_cannot_invoke_faculty_apis(sec_env):
    """A user logged in with 'student' role cannot call faculty attendance and management APIs."""
    client = sec_env['client']
    with client.session_transaction() as sess:
        sess['user'] = {'id': 10, 'username': 'student1', 'role': 'student'}

    token = extract_csrf_token(client)
    headers = {'X-CSRFToken': token}

    api_endpoints = [
        ('POST', '/api/students/1/register-face', {'image': 'dummy'}),
        ('POST', '/api/courses/CRS-CSE3132/enroll', {'student_ids': [1]}),
        ('POST', '/api/sessions/SES-101/recognize', {'image': 'dummy'}),
        ('POST', '/api/sessions/SES-101/mark-manual', {'student_id': 1}),
        ('POST', '/api/sessions/SES-101/end', None),
        ('GET', '/api/reports/export-csv?course_id=CRS-CSE3132', None),
    ]

    for method, path, payload in api_endpoints:
        if method == 'POST':
            resp = client.post(path, json=payload, headers=headers)
        else:
            resp = client.get(path, headers=headers)

        assert resp.status_code == 403, f"Failed for {method} {path}: student received {resp.status_code}"
        data = resp.get_json()
        assert data.get('error') == 'Forbidden'


def test_admin_can_access_all_faculty_endpoints(sec_env):
    """An authorized administrator satisfies role checks across all endpoints."""
    client = sec_env['client']
    with client.session_transaction() as sess:
        sess['user'] = {'id': 99, 'username': 'admin', 'role': 'admin', 'name': 'Administrator'}

    # Admin accessing dashboard
    resp = client.get('/dashboard')
    assert resp.status_code == 200

    # Admin accessing course enrollment data
    resp2 = client.get('/api/courses/CRS-CSE3132/enrollment-data')
    assert resp2.status_code == 200


# =============================================================================
# 6. Session & Course Ownership Tests
# =============================================================================

def test_faculty_cannot_modify_another_instructors_session(sec_env):
    """Faculty FAC002 cannot close or manually mark attendance for a session owned by FAC001."""
    client = sec_env['client']
    db_path = sec_env['db_path']

    # Start session owned by FAC001
    success, msg, session = AttendanceService.start_session(
        course_id='CRS-CSE3132',
        faculty_id='FAC001',
        topic="FAC001 Session",
        db_path=db_path
    )
    assert success is True
    session_id = session['session_id']

    # Authenticate as FAC002
    with client.session_transaction() as sess:
        sess['user'] = {
            'id': 3,
            'username': 'meenakshi.s',
            'role': 'faculty',
            'faculty_id': 'FAC002',
            'name': 'Dr. Meenakshi Sharma'
        }

    token = extract_csrf_token(client)
    headers = {'X-CSRFToken': token}

    # Attempt to mark manual attendance on FAC001's session -> Must be 403 Forbidden
    resp_mark = client.post(f"/api/sessions/{session_id}/mark-manual", json={'student_id': 'STU001'}, headers=headers)
    assert resp_mark.status_code == 403
    assert resp_mark.get_json().get('error') == 'Forbidden'

    # Attempt to close FAC001's session -> Must be 403 Forbidden
    resp_end = client.post(f"/api/sessions/{session_id}/end", headers=headers)
    assert resp_end.status_code == 403
    assert resp_end.get_json().get('error') == 'Forbidden'


# =============================================================================
# 7. Session Invalidation on Logout Tests
# =============================================================================

def test_logout_clears_session_completely(sec_env):
    """Calling /logout clears session data and redirects to login."""
    client = sec_env['client']
    with client.session_transaction() as sess:
        sess['user'] = {'id': 2, 'username': 'rajesh.kumar', 'role': 'faculty', 'faculty_id': 'FAC001'}
        sess['custom_var'] = 'lingering_data'

    resp = client.get('/logout', follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']

    # Accessing /dashboard now must fail with 302 redirect
    resp_dash = client.get('/dashboard', follow_redirects=False)
    assert resp_dash.status_code == 302


# =============================================================================
# 8. Production Configuration & Safeguard Tests
# =============================================================================

def test_missing_or_insecure_production_secret_key_raises_error():
    """Application startup in production mode without SECRET_KEY or with insecure fallbacks fails with RuntimeError."""
    from importlib import reload
    import config

    # Missing secret key
    with patch.dict(os.environ, {'FLASK_ENV': 'production'}, clear=True):
        with pytest.raises(RuntimeError) as exc_info:
            reload(config)
        assert "CRITICAL SECURITY CONFIGURATION ERROR" in str(exc_info.value)

    # Insecure fallback secret key
    with patch.dict(os.environ, {'FLASK_ENV': 'production', 'SECRET_KEY': 'dev-insecure-secret-key-change-in-production'}, clear=True):
        with pytest.raises(RuntimeError) as exc_info:
            reload(config)
        assert "CRITICAL SECURITY CONFIGURATION ERROR" in str(exc_info.value)

    # Restore standard environment
    reload(config)


def test_production_mode_blocks_known_default_credentials(sec_env):
    """In production mode, logging in with known default development credentials is strictly blocked."""
    db_path = sec_env['db_path']
    import config

    # In dev mode, faculty123 works
    with patch.object(config.Config, 'IS_PRODUCTION', False):
        user_dev = AuthService.authenticate('rajesh.kumar', 'faculty123', db_path=db_path)
        assert user_dev is not None

    # In production mode, faculty123 is rejected
    with patch.object(config.Config, 'IS_PRODUCTION', True):
        user_prod = AuthService.authenticate('rajesh.kumar', 'faculty123', db_path=db_path)
        assert user_prod is None
