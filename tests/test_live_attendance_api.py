"""
tests/test_live_attendance_api.py - Focused API and integration test suite
Verifies authoritative database-backed live attendance recording, duplicate prevention,
enrollment validation, session state persistence, and error handling.
"""

import os
import sqlite3
import pytest
from unittest.mock import patch

from database import init_db, seed_initial_data
from models import ClassSessionModel, AttendanceRecordModel
from attendance_service import AttendanceService
from face_recognition_service import face_service
from run_frontend_dev import app


@pytest.fixture
def live_api_env(tmp_path):
    """
    Sets up an isolated SQLite database and Flask test client
    with a pre-seeded course and active session.
    """
    db_file = str(tmp_path / "test_live_attendance.db")
    init_db(db_file)
    seed_initial_data(db_file)

    app.config['TESTING'] = True
    app.config['DB_PATH'] = db_file
    app.data_provider.db_path = db_file

    # Start an active session for CRS-CSE3132 (Software Engineering Lab)
    success, msg, session = AttendanceService.start_session(
        course_id='CRS-CSE3132',
        faculty_id='FAC001',
        topic="Consolidated Live Attendance Verification",
        db_path=db_file
    )
    assert success is True
    assert session is not None

    client = app.test_client()

    # Authenticate client as an authorized administrator capable of managing multi-faculty sessions
    with client.session_transaction() as sess:
        sess['user'] = {
            'id': 1,
            'username': 'admin',
            'role': 'admin',
            'name': 'System Administrator'
        }

    # Extract CSRF token from page meta tag and attach to test client headers
    res = client.get('/login')
    import re
    m = re.search(r'name="csrf-token" content="([^"]+)"', res.data.decode('utf-8'))
    if m:
        client.environ_base['HTTP_X_CSRFTOKEN'] = m.group(1)

    return {
        'client': client,
        'db_path': db_file,
        'session_id': session['session_id'],
        'course_id': 'CRS-CSE3132'
    }


def test_valid_recognised_enrolled_student_marked_once(live_api_env):
    """A valid recognized and enrolled student is marked present once in the persistent database."""
    client = live_api_env['client']
    session_id = live_api_env['session_id']
    db_path = live_api_env['db_path']

    mock_match = {
        'status': 'MATCHED',
        'student_id': 'STU001',
        'confidence': 0.942,
        'box': [100, 100, 80, 80],
        'message': "Student 'STU001' recognized with confidence 94.20%."
    }

    with patch.object(face_service, 'match_face', return_value=mock_match):
        resp = client.post(
            f"/api/sessions/{session_id}/recognize",
            json={'image': 'data:image/jpeg;base64,valid_mock_frame_data'}
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'marked'
    assert data['student']['student_id'] == 'STU001'
    assert data['confidence'] == 0.942
    assert data['method'] == 'FACE_RECOGNITION'

    # Verify directly in persistent SQLite database
    records = AttendanceRecordModel.get_session_attendance(session_id, db_path=db_path)
    assert len(records) == 1
    assert records[0]['student_id'] == 'STU001'
    assert records[0]['status'] == 'Present'


def test_repeated_request_does_not_create_second_attendance_record(live_api_env):
    """A repeated recognize request does not create a duplicate record in the database."""
    client = live_api_env['client']
    session_id = live_api_env['session_id']
    db_path = live_api_env['db_path']

    mock_match = {
        'status': 'MATCHED',
        'student_id': 'STU001',
        'confidence': 0.95,
        'box': [100, 100, 80, 80],
        'message': "Student 'STU001' recognized."
    }

    with patch.object(face_service, 'match_face', return_value=mock_match):
        # First attendance mark -> Success
        resp1 = client.post(
            f"/api/sessions/{session_id}/recognize",
            json={'image': 'data:image/jpeg;base64,frame1'}
        )
        assert resp1.status_code == 200
        assert resp1.get_json()['status'] == 'marked'

        # Second attendance mark -> Blocked as duplicate
        resp2 = client.post(
            f"/api/sessions/{session_id}/recognize",
            json={'image': 'data:image/jpeg;base64,frame2'}
        )
        assert resp2.status_code == 200
        data2 = resp2.get_json()
        assert data2['status'] == 'already_marked'
        assert "duplicate" in data2['message'].lower() or "already marked" in data2['message'].lower()

    # Verify directly in SQLite that only 1 record exists
    records = AttendanceRecordModel.get_session_attendance(session_id, db_path=db_path)
    assert len(records) == 1


def test_unrecognised_face_cannot_create_attendance(live_api_env):
    """An unrecognized face must not create any attendance record."""
    client = live_api_env['client']
    session_id = live_api_env['session_id']
    db_path = live_api_env['db_path']

    mock_unknown = {
        'status': 'UNKNOWN_FACE',
        'student_id': None,
        'confidence': 0.42,
        'box': [50, 50, 60, 60],
        'message': "Face detected below threshold."
    }

    with patch.object(face_service, 'match_face', return_value=mock_unknown):
        resp = client.post(
            f"/api/sessions/{session_id}/recognize",
            json={'image': 'data:image/jpeg;base64,unknown_frame'}
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'unrecognized'

    # Verify persistent database is unchanged
    records = AttendanceRecordModel.get_session_attendance(session_id, db_path=db_path)
    assert len(records) == 0


def test_student_not_enrolled_cannot_be_marked(live_api_env):
    """A student registered in the system but not enrolled in this course cannot be marked."""
    client = live_api_env['client']
    db_path = live_api_env['db_path']

    # Start a session for CRS-CSE3101 (only STU001-STU005 are enrolled; STU007 is NOT enrolled)
    success, _, sess_cse3101 = AttendanceService.start_session(
        course_id='CRS-CSE3101',
        faculty_id='FAC002',
        topic="OS Lab",
        db_path=db_path
    )
    assert success is True
    sess_id = sess_cse3101['session_id']

    mock_match = {
        'status': 'MATCHED',
        'student_id': 'STU007',
        'confidence': 0.93,
        'box': [100, 100, 80, 80],
        'message': "Student 'STU007' recognized."
    }

    with patch.object(face_service, 'match_face', return_value=mock_match):
        resp = client.post(
            f"/api/sessions/{sess_id}/recognize",
            json={'image': 'data:image/jpeg;base64,frame_stu007'}
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'not_enrolled'
    assert "not enrolled" in data['message'].lower() or "enrollment error" in data['message'].lower()

    # Verify no attendance record in DB
    records = AttendanceRecordModel.get_session_attendance(sess_id, db_path=db_path)
    assert len(records) == 0


def test_inactive_or_closed_session_rejects_attendance(live_api_env):
    """Attendance requests to an inactive or closed session must be rejected."""
    client = live_api_env['client']
    session_id = live_api_env['session_id']
    db_path = live_api_env['db_path']

    # Close session via service
    close_ok, close_msg, _ = AttendanceService.close_session(session_id, db_path=db_path)
    assert close_ok is True

    mock_match = {
        'status': 'MATCHED',
        'student_id': 'STU001',
        'confidence': 0.96,
        'box': [100, 100, 80, 80],
        'message': "Student 'STU001' recognized."
    }

    with patch.object(face_service, 'match_face', return_value=mock_match):
        resp = client.post(
            f"/api/sessions/{session_id}/recognize",
            json={'image': 'data:image/jpeg;base64,frame_after_close'}
        )

    assert resp.status_code == 400
    data = resp.get_json()
    assert data['status'] == 'session_inactive'
    assert "completed" in data['message'].lower() or "active" in data['message'].lower()

    # Verify persistent DB has zero attendance
    records = AttendanceRecordModel.get_session_attendance(session_id, db_path=db_path)
    assert len(records) == 0


def test_ending_session_changes_persisted_state(live_api_env):
    """Calling the session end endpoint changes the session status in the database to Completed."""
    client = live_api_env['client']
    session_id = live_api_env['session_id']
    db_path = live_api_env['db_path']

    # Initial state is Active
    session_before = ClassSessionModel.get_by_id(session_id, db_path=db_path)
    assert session_before['status'] == 'Active'
    assert session_before['end_time'] is None

    # Conclude session via endpoint
    resp = client.post(f"/api/sessions/{session_id}/end")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'success'

    # Verify persisted state in SQLite database
    session_after = ClassSessionModel.get_by_id(session_id, db_path=db_path)
    assert session_after['status'] == 'Completed'
    assert session_after['end_time'] is not None

    # Calling end again should fail because session is already completed
    resp_again = client.post(f"/api/sessions/{session_id}/end")
    assert resp_again.status_code == 400
    data_again = resp_again.get_json()
    assert data_again['status'] == 'error'


def test_database_write_failure_not_reported_as_success(live_api_env):
    """If an insert into the database fails, the API must not report a successful attendance mark."""
    client = live_api_env['client']
    session_id = live_api_env['session_id']
    db_path = live_api_env['db_path']

    mock_match = {
        'status': 'MATCHED',
        'student_id': 'STU001',
        'confidence': 0.95,
        'box': [100, 100, 80, 80],
        'message': "Student 'STU001' recognized."
    }

    with patch.object(face_service, 'match_face', return_value=mock_match):
        # Simulate an unexpected database write error (e.g. disk corruption, locked file)
        with patch('models.AttendanceRecordModel.record_attendance', side_effect=sqlite3.OperationalError("disk I/O error")):
            resp = client.post(
                f"/api/sessions/{session_id}/recognize",
                json={'image': 'data:image/jpeg;base64,frame_failing'}
            )

    # API must NOT report status 'marked' or claim success
    assert resp.status_code in (500, 400)
    data = resp.get_json()
    assert data['status'] != 'marked'
    assert data.get('status') == 'error'

    # Verify no phantom record in database
    records = AttendanceRecordModel.get_session_attendance(session_id, db_path=db_path)
    assert len(records) == 0


def test_missing_image_payload_returns_400(live_api_env):
    """Requests with missing image data return HTTP 400 Bad Request."""
    client = live_api_env['client']
    session_id = live_api_env['session_id']

    resp = client.post(f"/api/sessions/{session_id}/recognize", json={})
    assert resp.status_code == 400
    data = resp.get_json()
    assert "missing" in data.get('error', '').lower() or "missing" in data.get('message', '').lower()

