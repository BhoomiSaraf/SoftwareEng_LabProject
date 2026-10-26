"""
test_backend.py - Comprehensive automated test suite for Backend & Database module.
Tests:
- Database initialization and seed data
- Authentication & role verification
- Student, Faculty, Course, and Enrollment operations
- Session lifecycle (Start, Query, Close)
- Centralized attendance engine & strict duplicate prevention
- Inactive session rejection
- Non-enrolled student rejection
- Attendance percentage calculations & low-attendance flags
- CSV generation
"""

import os
import pytest
from database import init_db, seed_initial_data, get_db_connection
from auth import AuthService
from models import (
    StudentModel,
    FacultyModel,
    CourseModel,
    EnrollmentModel,
    ClassSessionModel,
    AttendanceRecordModel
)
from attendance_service import AttendanceService


@pytest.fixture
def test_db(tmp_path):
    """Fixture that initializes a clean SQLite database for each test."""
    db_file = str(tmp_path / "test_smart_attendance.db")
    init_db(db_file)
    seed_initial_data(db_file)
    return db_file


def test_database_initialization_and_seeding(test_db):
    """Verify that all core tables exist and initial academic seed data is loaded."""
    conn = get_db_connection(test_db)
    cursor = conn.cursor()

    # Check student count
    cursor.execute("SELECT COUNT(*) AS count FROM students;")
    assert cursor.fetchone()['count'] == 8

    # Check course count
    cursor.execute("SELECT COUNT(*) AS count FROM courses;")
    assert cursor.fetchone()['count'] == 4

    # Check faculty count
    cursor.execute("SELECT COUNT(*) AS count FROM faculty;")
    assert cursor.fetchone()['count'] == 2

    # Check that Bhoomi Saraf is seeded
    bhoomi = StudentModel.get_by_roll('229301045', test_db)
    assert bhoomi is not None
    assert bhoomi['name'] == 'Bhoomi Saraf'
    assert bhoomi['program'] == 'B.Tech CSE'
    conn.close()


def test_auth_service(test_db):
    """Verify password hashing, credential verification, and role checks."""
    # Authenticate seeded faculty
    fac_user = AuthService.authenticate('rajesh.kumar', 'faculty123', test_db)
    assert fac_user is not None
    assert fac_user['role'] == 'faculty'
    assert AuthService.has_role(fac_user, 'faculty') is True
    assert AuthService.has_role(fac_user, 'admin') is False

    # Authenticate seeded admin
    admin_user = AuthService.authenticate('admin', 'admin123', test_db)
    assert admin_user is not None
    assert admin_user['role'] == 'admin'
    # Admin has access to all roles
    assert AuthService.has_role(admin_user, 'faculty') is True

    # Bad password
    bad_login = AuthService.authenticate('rajesh.kumar', 'wrong_pass', test_db)
    assert bad_login is None

    # Create new student user
    new_user = AuthService.create_user('test.student', 'pass456', 'student', test_db)
    assert new_user is not None
    assert new_user['username'] == 'test.student'
    assert new_user['role'] == 'student'


def test_models_student_and_enrollment(test_db):
    """Verify student and course enrollment query operations."""
    course_id = 'CRS-CSE3132'

    # Enrolled students
    enrolled = EnrollmentModel.get_enrolled_students(course_id, test_db)
    assert len(enrolled) == 8

    # Check specific enrollment
    assert EnrollmentModel.is_enrolled(course_id, 'STU001', test_db) is True

    # Check non-enrolled student for CSE3101 (only first 5 students enrolled)
    assert EnrollmentModel.is_enrolled('CRS-CSE3101', 'STU007', test_db) is False


def test_session_lifecycle(test_db):
    """Verify session creation and closure."""
    course_id = 'CRS-CSE3132'
    fac_id = 'FAC001'

    # Start session
    success, msg, session = AttendanceService.start_session(
        course_id=course_id,
        faculty_id=fac_id,
        topic="Lab 3 Class Modeling",
        db_path=test_db
    )
    assert success is True
    assert session['status'] == 'Active'
    assert session['course_id'] == course_id

    session_id = session['session_id']

    # Verify active query
    active = ClassSessionModel.get_active_session_for_course(course_id, test_db)
    assert active is not None
    assert active['session_id'] == session_id

    # Close session
    close_success, close_msg, closed_sess = AttendanceService.close_session(session_id, test_db)
    assert close_success is True
    assert closed_sess['status'] == 'Completed'
    assert closed_sess['end_time'] is not None

    # Verify no active session remaining
    active_after = ClassSessionModel.get_active_session_for_course(course_id, test_db)
    assert active_after is None


def test_attendance_marking_and_duplicate_prevention(test_db):
    """
    CRITICAL LAB TEST:
    1. Mark student present.
    2. Try marking same student again in same session -> DUPLICATE BLOCKED.
    3. Try marking non-enrolled student -> BLOCKED.
    4. Try marking in closed session -> BLOCKED.
    """
    course_id = 'CRS-CSE3132'
    fac_id = 'FAC001'

    # 1. Start session
    _, _, session = AttendanceService.start_session(course_id, fac_id, db_path=test_db)
    sess_id = session['session_id']

    # 2. Mark attendance for Bhoomi (STU001)
    ok, msg, rec = AttendanceService.record_attendance(
        session_id=sess_id,
        student_id='STU001',
        method='Face Recognition',
        confidence_score=0.98,
        db_path=test_db
    )
    assert ok is True
    assert 'Present' in msg
    assert rec['student_name'] == 'Bhoomi Saraf'

    # 3. Duplicate attempt for STU001 -> MUST FAIL
    dup_ok, dup_msg, dup_rec = AttendanceService.record_attendance(
        session_id=sess_id,
        student_id='STU001',
        method='Face Recognition',
        db_path=test_db
    )
    assert dup_ok is False
    assert 'Duplicate attendance blocked' in dup_msg
    assert dup_rec['student_id'] == 'STU001'

    # 4. Try marking STU007 in CSE3101 (where STU007 is NOT enrolled)
    _, _, sess_other = AttendanceService.start_session('CRS-CSE3101', 'FAC002', db_path=test_db)
    not_enrolled_ok, not_enrolled_msg, _ = AttendanceService.record_attendance(
        session_id=sess_other['session_id'],
        student_id='STU007',
        db_path=test_db
    )
    assert not_enrolled_ok is False
    assert 'not enrolled' in not_enrolled_msg

    # 5. Close session and try marking -> MUST FAIL
    AttendanceService.close_session(sess_id, test_db)
    closed_ok, closed_msg, _ = AttendanceService.record_attendance(
        session_id=sess_id,
        student_id='STU002',
        db_path=test_db
    )
    assert closed_ok is False
    assert 'Attendance rejected' in closed_msg


def test_attendance_reports_and_percentages(test_db):
    """
    Verify attendance percentage calculations and low-attendance (<75%) indicators.
    Conduct 4 sessions.
    - STU001 attends 4/4 = 100% (No warning)
    - STU002 attends 2/4 = 50% (Low attendance warning TRUE)
    """
    course_id = 'CRS-CSE3132'
    fac_id = 'FAC001'

    # Conduct 4 sessions
    for i in range(1, 5):
        _, _, s = AttendanceService.start_session(course_id, fac_id, topic=f"Lab session {i}", db_path=test_db)
        sid = s['session_id']

        # STU001 attends all 4
        AttendanceService.record_attendance(sid, 'STU001', db_path=test_db)

        # STU002 attends only session 1 and 2
        if i <= 2:
            AttendanceService.record_attendance(sid, 'STU002', db_path=test_db)

        AttendanceService.close_session(sid, test_db)

    report = AttendanceService.get_course_attendance_report(course_id, test_db)
    assert report['total_sessions_held'] == 4

    stu_map = {r['student_id']: r for r in report['student_reports']}

    # STU001
    assert stu_map['STU001']['attended_sessions'] == 4
    assert stu_map['STU001']['attendance_percentage'] == 100.0
    assert stu_map['STU001']['low_attendance_warning'] is False

    # STU002
    assert stu_map['STU002']['attended_sessions'] == 2
    assert stu_map['STU002']['attendance_percentage'] == 50.0
    assert stu_map['STU002']['low_attendance_warning'] is True


def test_manual_override(test_db):
    """Verify faculty can manually correct attendance."""
    course_id = 'CRS-CSE3132'
    _, _, session = AttendanceService.start_session(course_id, 'FAC001', db_path=test_db)
    _, _, rec = AttendanceService.record_attendance(session['session_id'], 'STU001', db_path=test_db)

    # Change to Late
    ok, msg = AttendanceService.manual_override(rec['attendance_id'], 'Late', faculty_name="Dr. Rajesh Kumar", db_path=test_db)
    assert ok is True

    # Verify updated record
    records = AttendanceRecordModel.get_session_attendance(session['session_id'], test_db)
    assert records[0]['status'] == 'Late'
    assert records[0]['marking_method'] == 'Manual Override'


def test_csv_export(test_db):
    """Verify RFC 4180 CSV export generation."""
    course_id = 'CRS-CSE3132'
    _, _, s = AttendanceService.start_session(course_id, 'FAC001', db_path=test_db)
    AttendanceService.record_attendance(s['session_id'], 'STU001', db_path=test_db)
    AttendanceService.close_session(s['session_id'], test_db)

    csv_data = AttendanceService.generate_csv_report(course_id, test_db)
    assert "MANIPAL UNIVERSITY JAIPUR" in csv_data
    assert "CSE3132" in csv_data
    assert "Bhoomi Saraf" in csv_data
    assert "100.0%" in csv_data
