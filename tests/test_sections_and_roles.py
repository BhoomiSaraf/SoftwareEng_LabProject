"""
tests/test_sections_and_roles.py - Tests for Role-based UI restrictions (Admin vs Faculty)
and Section-wise student management & attendance validation.
"""
import re
import pytest
import sqlite3
from database import init_db, seed_initial_data
from models import StudentModel, ClassSessionModel, EnrollmentModel, AttendanceRecordModel
from attendance_service import AttendanceService
from run_frontend_dev import app


def extract_csrf_token(client):
    resp = client.get('/login')
    match = re.search(r'name="csrf_token" value="([^"]+)"', resp.data.decode('utf-8'))
    if match:
        return match.group(1)
    match_meta = re.search(r'name="csrf-token" content="([^"]+)"', resp.data.decode('utf-8'))
    if match_meta:
        return match_meta.group(1)
    return "test-token"


@pytest.fixture
def test_env(tmp_path):
    orig_db = app.config.get('DB_PATH')
    orig_dp_db = getattr(app.data_provider, 'db_path', None)

    db_file = str(tmp_path / "test_roles_sections.db")
    init_db(db_file)
    seed_initial_data(db_file)

    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['DB_PATH'] = db_file
    app.data_provider.db_path = db_file

    client = app.test_client()

    yield {
        'client': client,
        'db_path': db_file
    }

    app.config['DB_PATH'] = orig_db
    if orig_dp_db:
        app.data_provider.db_path = orig_dp_db


def test_section_schema_migration_and_defaults(test_env):
    """Verify that section defaults to 'A' for students and 'All' for class sessions."""
    db_path = test_env['db_path']

    # Create student with default section
    st = StudentModel.create(
        student_id='STU099',
        roll_number='TEST999',
        name='Test Section Student',
        email='test.section@college.edu',
        program='B.Tech CSE',
        semester=5,
        db_path=db_path
    )
    assert st['section'] == 'A'

    # Create student with explicit section 'B'
    st_b = StudentModel.create(
        student_id='STU100',
        roll_number='TEST100',
        name='Section B Student',
        email='test.b@college.edu',
        program='B.Tech CSE',
        semester=5,
        section='B',
        db_path=db_path
    )
    assert st_b['section'] == 'B'


def test_section_mismatch_attendance_rejection(test_env):
    """A session restricted to Section A rejects attendance for a student enrolled in Section B."""
    db_path = test_env['db_path']

    # Create student in Section B
    st_b = StudentModel.create(
        student_id='STU101',
        roll_number='21BCE099',
        name='Student In Sec B',
        email='sec.b@college.edu',
        program='B.Tech CSE',
        semester=5,
        section='B',
        db_path=db_path
    )
    
    # Enroll in course CRS-CSE3132
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO enrollments (course_id, student_id) VALUES (?, ?);", ('CRS-CSE3132', st_b['student_id']))
    conn.commit()
    conn.close()

    # Start session restricted to Section A
    ok, msg, session = AttendanceService.start_session(
        course_id='CRS-CSE3132',
        faculty_id='FAC001',
        section='A',
        db_path=db_path
    )
    assert ok is True
    session_id = session['session_id']

    # Attempt to record attendance for Section B student in Section A session -> Must fail with section mismatch
    rec_ok, rec_msg, rec = AttendanceService.record_attendance(
        session_id=session_id,
        student_id=st_b['student_id'],
        db_path=db_path
    )
    assert rec_ok is False
    assert "Section Mismatch" in rec_msg

    # Now start a session for 'All' sections
    ok_all, msg_all, session_all = AttendanceService.start_session(
        course_id='CRS-CSE3132',
        faculty_id='FAC001',
        section='All',
        db_path=db_path
    )
    assert ok_all is True
    session_all_id = session_all['session_id']

    # Attendance for Section B student in 'All' session -> Must succeed
    rec_all_ok, rec_all_msg, rec_all = AttendanceService.record_attendance(
        session_id=session_all_id,
        student_id=st_b['student_id'],
        db_path=db_path
    )
    assert rec_all_ok is True
    assert rec_all['status'] == 'Present'


def test_non_admin_cannot_create_course(test_env):
    """Faculty cannot create courses through /actions/courses/create (strictly restricted to Admin)."""
    client = test_env['client']

    with client.session_transaction() as sess:
        sess['user'] = {
            'id': 2,
            'username': 'rajesh.kumar',
            'role': 'faculty',
            'faculty_id': 'FAC001'
        }

    token = extract_csrf_token(client)
    resp = client.post(
        '/actions/courses/create',
        data={'code': 'CS999', 'name': 'Unauthorized Course', 'csrf_token': token},
        follow_redirects=True
    )
    assert resp.status_code == 403
    assert b'Access denied' in resp.data or b'admin' in resp.data


def test_non_admin_cannot_register_student(test_env):
    """Faculty cannot register students through /actions/students/add (strictly restricted to Admin)."""
    client = test_env['client']

    with client.session_transaction() as sess:
        sess['user'] = {
            'id': 2,
            'username': 'rajesh.kumar',
            'role': 'faculty',
            'faculty_id': 'FAC001'
        }

    token = extract_csrf_token(client)
    resp = client.post(
        '/actions/students/add',
        data={'roll_no': '21BCE999', 'name': 'Hacked Student', 'email': 'hacked@college.edu', 'csrf_token': token},
        follow_redirects=True
    )
    assert resp.status_code == 403
    assert b'Access denied' in resp.data or b'admin' in resp.data
