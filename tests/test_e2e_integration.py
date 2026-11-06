"""
tests/test_e2e_integration.py - Comprehensive End-to-End Behavioral & Integration Test Suite.

Validates the complete Smart Attendance workflow on isolated SQLite databases:
1. Student creation persists across fresh database connections without auto-enrollment fallbacks.
2. Faculty assignment, course creation with custom credits/semester/academic_year, and faculty authorization checks.
3. Enrollment persists and rejects duplicate or invalid relationships.
4. Face-encoding persistence: uses configured EMBEDDINGS_FILE path, verifies disk persistence,
   reloads across restarts, and verifies honest 500 error when disk persistence fails (never marking
   face_registered in SQLite without persisted embeddings).
5. Deterministic biometric test scenarios (labeled accurately as synthetic regression tests):
   - No face detected -> status 'no_face'
   - Multiple faces detected -> status 'multiple_faces'
   - Unrecognized face -> status 'unrecognized'
   - Valid recognized enrolled student -> status 'marked' (exactly 1 record in SQLite)
   - Repeated face recognition -> status 'already_marked' (duplicate prevention)
   - Recognized but non-enrolled student -> status 'not_enrolled'
   - Session inactive / closed -> status 'session_inactive' (HTTP 400)
   - Non-existent session -> HTTP 404
6. True application restart persistence: records and registered embeddings survive complete process/memory reset.
7. Complete CSV export coverage:
   - course_id=all with >= 2 courses and distinct attendance records (no omissions or duplicates)
   - Correct RFC 4180 headers and percentage formatting (X.X%)
   - Course with 0 attendance sessions
   - Invalid course_id returns HTTP 404
   - Proper CSV field escaping for special characters (commas, quotes)
8. Honest error responses for invalid identifiers without demo/sample fallbacks.

MANUAL PHYSICAL CAMERA VERIFICATION PROTOCOL:
Automated test suite tests use synthetic frames and controlled Haar/MobileNetV3 feature inputs to ensure
deterministic reproducibility across headless CI/CD environments. Physical optical validation requires:
1. Hardware: USB / integrated webcam with >= 720p resolution and normal ambient lighting (300-500 lux).
2. Live Webcam Enrollment: Run `python enroll_bhoomi.py` or navigate to `/students` -> Enroll Face in browser.
   Position face in the center frame guide until bounding box turns green and 5 samples are captured.
3. Live Webcam Attendance: Login as faculty -> Navigate to `/dashboard` -> Click 'Start Session' ->
   Point camera at enrolled student -> Confirm real-time banner displays student name and roll number.
"""

import os
import io
import csv
import re
import tempfile
import base64
import pytest
import sqlite3
import numpy as np
import cv2

from database import init_db, get_db_connection
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
from face_recognition_service import face_service, FaceRecognitionService
from data_provider import DataProvider
from run_frontend_dev import app
from config import Config


def _set_role(client, role):
    """Face enrolment and roster editing are admin-only; sessions are run by faculty."""
    with client.session_transaction() as sess:
        sess["user"] = {**sess["user"], "role": role}


@pytest.fixture
def e2e_env(tmp_path):
    """Creates a completely isolated SQLite database, configured embeddings path, and test client."""
    db_file = str(tmp_path / "e2e_attendance.db")
    embeddings_file = str(tmp_path / "e2e_embeddings.npz")

    # Initialize empty schema
    init_db(db_file)

    # Create admin and 2 distinct faculty users for multi-faculty tests
    admin_user = AuthService.create_user("admin_test", "admin123", "admin", db_path=db_file)
    fac_user1 = AuthService.create_user("faculty_test1", "faculty123", "faculty", db_path=db_file)
    fac_user2 = AuthService.create_user("faculty_test2", "faculty123", "faculty", db_path=db_file)

    # Insert faculty profiles
    conn = get_db_connection(db_file)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO faculty (faculty_id, user_id, name, email, department) VALUES (?, ?, ?, ?, ?);",
        ("FAC001", fac_user1["id"], "Prof. Alan Turing", "turing@college.edu", "Computer Science")
    )
    cursor.execute(
        "INSERT INTO faculty (faculty_id, user_id, name, email, department) VALUES (?, ?, ?, ?, ?);",
        ("FAC002", fac_user2["id"], "Dr. Ada Lovelace", "lovelace@college.edu", "Computer Science")
    )
    conn.commit()
    conn.close()

    # Clear face registry for isolated testing
    face_service.clear_registry()

    # Save original app state
    orig_db_path = app.config.get("DB_PATH")
    orig_emb_path = app.config.get("EMBEDDINGS_FILE")
    orig_dp = getattr(app, "data_provider", None)
    orig_cfg_emb = getattr(Config, "EMBEDDINGS_FILE", None)

    # Configure app for isolated environment
    app.config["TESTING"] = True
    app.config["DB_PATH"] = db_file
    app.config["EMBEDDINGS_FILE"] = embeddings_file
    Config.EMBEDDINGS_FILE = embeddings_file

    dp = DataProvider(db_path=db_file, embeddings_path=embeddings_file)
    app.data_provider = dp

    client = app.test_client()

    # Authenticate as faculty FAC001 by default
    with client.session_transaction() as sess:
        sess["user"] = {
            "id": fac_user1["id"],
            "username": "faculty_test1",
            "name": "Prof. Alan Turing",
            "email": "turing@college.edu",
            "role": "faculty",
            "faculty_id": "FAC001"
        }

    # Fetch CSRF token
    res = client.get("/login")
    m = re.search(r'name="csrf-token" content="([^"]+)"', res.data.decode("utf-8"))
    csrf_token = m.group(1) if m else "test-token"
    client.environ_base["HTTP_X_CSRFTOKEN"] = csrf_token

    yield {
        "db_path": db_file,
        "embeddings_file": embeddings_file,
        "client": client,
        "csrf_token": csrf_token,
        "data_provider": dp,
        "faculty_id": "FAC001",
        "faculty_id_2": "FAC002",
        "fac_user1": fac_user1,
        "fac_user2": fac_user2,
    }

    # Teardown: restore original app state
    face_service.clear_registry()
    app.config["DB_PATH"] = orig_db_path
    app.config["EMBEDDINGS_FILE"] = orig_emb_path
    app.data_provider = orig_dp
    Config.EMBEDDINGS_FILE = orig_cfg_emb


def test_1_student_creation_and_persistence(e2e_env):
    """Step 1: Student creation persists and survives a fresh database connection."""
    dp = e2e_env["data_provider"]
    db_path = e2e_env["db_path"]

    # Create student via data_provider
    created = dp.create_student(
        roll_no="229301999",
        name="Integration Test Student",
        email="integration.test@college.edu",
        program="B.Tech CSE",
        semester=5
    )
    assert created is not None
    assert created["roll_no"] == "229301999"
    assert created["course_codes"] == []  # Must not auto-enroll in arbitrary courses

    # Verify directly via an independent, fresh database connection
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE roll_number = '229301999';")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row["name"] == "Integration Test Student"
    assert row["face_registered"] == 0


def test_2_faculty_assignment_and_course_attributes(e2e_env):
    """
    Step 2: Validate faculty assignment, custom course attributes, and faculty authorization:
    - Rejects missing faculty_id with ValueError.
    - Rejects nonexistent faculty_id with ValueError.
    - Validates credits > 0 and 1 <= semester <= 12.
    - Persists custom credits, semester, and academic_year.
    - Enforces AttendanceService session authorization: faculty cannot start session for another's course.
    """
    dp = e2e_env["data_provider"]
    db_path = e2e_env["db_path"]
    client = e2e_env["client"]

    # 1. Missing faculty_id must raise ValueError
    with pytest.raises(ValueError, match="Faculty assignment is required"):
        dp.create_course("CS100", "No Faculty Course", faculty_id=None)

    # 2. Nonexistent faculty_id must raise ValueError
    with pytest.raises(ValueError, match="does not exist"):
        dp.create_course("CS100", "Invalid Faculty Course", faculty_id="NONEXISTENT_FAC")

    # 3. Invalid credits must raise ValueError
    with pytest.raises(ValueError, match="Invalid course credits"):
        dp.create_course("CS100", "Bad Credits", faculty_id="FAC001", credits=0)

    # 4. Invalid semester must raise ValueError
    with pytest.raises(ValueError, match="Invalid semester"):
        dp.create_course("CS100", "Bad Semester", faculty_id="FAC001", semester=15)

    # 5. Successful course creation with custom attributes for FAC001
    course1 = dp.create_course(
        code="CS501",
        name="Advanced Algorithms",
        description="Core algorithms",
        faculty_id="FAC001",
        credits=4,
        semester=6,
        academic_year="2026-2027"
    )
    assert course1 is not None
    assert course1["faculty_id"] == "FAC001"
    assert course1["credits"] == 4
    assert course1["semester"] == 6
    assert course1["academic_year"] == "2026-2027"

    # 6. Create second course assigned to FAC002
    course2 = dp.create_course(
        code="CS502",
        name="Quantum Computing",
        description="Intro to Quantum",
        faculty_id="FAC002",
        credits=3,
        semester=7,
        academic_year="2026-2027"
    )
    assert course2["faculty_id"] == "FAC002"

    # 7. AttendanceService.start_session validation:
    # - Missing faculty_id rejected
    ok, msg, _ = AttendanceService.start_session("CRS-CS501", faculty_id=None, db_path=db_path)
    assert ok is False
    assert "Faculty assignment is required" in msg

    # - Nonexistent faculty rejected
    ok, msg, _ = AttendanceService.start_session("CRS-CS501", faculty_id="UNKNOWN_FAC", db_path=db_path)
    assert ok is False
    assert "does not exist" in msg

    # - Faculty FAC002 attempting to start session for FAC001's course (CRS-CS501) rejected
    ok, msg, _ = AttendanceService.start_session("CRS-CS501", faculty_id="FAC002", db_path=db_path)
    assert ok is False
    assert "not authorized to start session" in msg

    # - Faculty FAC001 starting session for own course CRS-CS501 succeeds
    ok, msg, sess = AttendanceService.start_session("CRS-CS501", faculty_id="FAC001", db_path=db_path)
    assert ok is True
    assert sess["status"] == "Active"
    AttendanceService.close_session(sess["session_id"], db_path=db_path)


def test_3_enrollment_lifecycle_and_duplicate_rejection(e2e_env):
    """Step 3: Enrollment persists in SQLite and duplicate or invalid enrollments are rejected."""
    dp = e2e_env["data_provider"]
    db_path = e2e_env["db_path"]
    client = e2e_env["client"]

    st = dp.create_student("229301001", "Student One", "s1@college.edu")
    cr = dp.create_course("CS101", "Intro to CS", faculty_id="FAC001")

    # Enroll via API (admin only)
    _set_role(client, "admin")
    resp = client.post(f"/api/courses/{cr['course_id']}/enroll", json={
        "student_ids": [st["student_id"]]
    })
    assert resp.status_code == 200

    # Verify in DB
    assert EnrollmentModel.is_enrolled(cr["course_id"], st["student_id"], db_path=db_path) is True

    # Duplicate enrollment attempt in DB fails safely without duplicating rows
    ok = EnrollmentModel.enroll_student(cr["course_id"], st["student_id"], db_path=db_path)
    assert ok is False  # Unique constraint violated

    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS count FROM enrollments WHERE course_id = ? AND student_id = ?;", (cr["course_id"], st["student_id"]))
    assert cursor.fetchone()["count"] == 1
    conn.close()


def test_4_face_encoding_persistence_and_failure_honesty(e2e_env):
    """
    Step 4: Unify face-encoding persistence and verify failure honesty:
    - Uses the configured EMBEDDINGS_FILE path.
    - Confirms the .npz file is written to configured storage.
    - Verifies student embeddings reload across service re-creation.
    - Verifies registration fails honestly (HTTP 500) if saving embeddings fails,
      and student face_registered is NOT set to 1 in the database.
    """
    dp = e2e_env["data_provider"]
    db_path = e2e_env["db_path"]
    client = e2e_env["client"]
    embeddings_file = e2e_env["embeddings_file"]

    st = dp.create_student("229301002", "Student Two", "s2@college.edu")

    # Create synthetic frame with distinct feature pattern
    frame = np.ones((200, 200, 3), dtype=np.uint8) * 180
    cv2.circle(frame, (80, 80), 40, (30, 60, 90), -1)
    _, buf = cv2.imencode(".jpg", frame)
    b64_frame = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("utf-8")

    orig_detect = face_service.detect_faces
    try:
        face_service.detect_faces = lambda img: [(20, 20, 120, 120)]
        _set_role(client, "admin")

        # 1. Register face through API
        resp = client.post(f"/api/students/{st['student_id']}/register-face", json={
            "image": b64_frame
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["embedding_dim"] == 576

        # 2. Verify configured embeddings file on disk was written
        assert os.path.exists(embeddings_file)

        # 3. Clear memory registry and reload from disk
        face_service.clear_registry()
        assert len(face_service.get_registered_student_ids()) == 0
        loaded = face_service.load_embeddings(embeddings_file)
        assert loaded is True
        assert st["student_id"] in face_service.get_registered_student_ids()

        # 4. Verify DB student has face_registered = 1
        st_db = StudentModel.get_by_id(st["student_id"], db_path=db_path)
        assert st_db["face_registered"] == 1

        # 5. Failure honesty check:
        # Create another student; mock save_embeddings to fail
        st_fail = dp.create_student("229301003", "Student Three", "s3@college.edu")
        orig_save = face_service.save_embeddings
        try:
            face_service.save_embeddings = lambda path: False

            fail_resp = client.post(f"/api/students/{st_fail['student_id']}/register-face", json={
                "image": b64_frame
            })
            assert fail_resp.status_code == 500
            assert "Failed to persist face embedding" in fail_resp.get_json()["message"]

            # Must NOT be marked as face_registered in SQLite database!
            st_fail_db = StudentModel.get_by_id(st_fail["student_id"], db_path=db_path)
            assert st_fail_db["face_registered"] == 0
        finally:
            face_service.save_embeddings = orig_save

    finally:
        face_service.detect_faces = orig_detect


def test_5_biometric_scenarios_deterministic_and_synthetic(e2e_env):
    """
    Step 5: Deterministic regression tests covering all biometric decision branches.
    
    [DETERMINISTIC REGRESSION TEST - SYNTHETIC INPUT]:
    Uses controlled pixel arrays and simulated detector coordinates to deterministically verify:
    - NO_FACE_DETECTED -> status 'no_face' (HTTP 200)
    - MULTIPLE_FACES_DETECTED -> status 'multiple_faces' (HTTP 200)
    - UNKNOWN_FACE -> status 'unrecognized' (HTTP 200)
    - Enrolled student MATCHED -> status 'marked' (HTTP 200, 1 SQLite record)
    - Repeated presentation -> status 'already_marked' (HTTP 200, 0 new records)
    - Non-enrolled student MATCHED -> status 'not_enrolled' (HTTP 200)
    - Inactive / closed session -> status 'session_inactive' (HTTP 400)
    - Nonexistent session -> status 'error' (HTTP 404)
    """
    dp = e2e_env["data_provider"]
    db_path = e2e_env["db_path"]
    client = e2e_env["client"]

    # 1. Setup Student 1 (Alice - enrolled) and Student 2 (Bob - non-enrolled)
    s1 = dp.create_student("229301010", "Alice Smith", "alice@college.edu")
    s2 = dp.create_student("229301020", "Bob Jones", "bob@college.edu")

    # 2. Setup Course CS501 assigned to FAC001
    course = dp.create_course("CS501", "Advanced Algorithms", faculty_id="FAC001")
    course_id = course["course_id"]

    # 3. Enroll only Alice
    EnrollmentModel.enroll_student(course_id, s1["student_id"], db_path=db_path)

    # 4. Generate distinct synthetic image frames
    alice_img = np.ones((200, 200, 3), dtype=np.uint8) * 160
    cv2.rectangle(alice_img, (30, 30), (120, 120), (50, 80, 100), -1)
    _, buf = cv2.imencode(".jpg", alice_img)
    alice_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("utf-8")

    bob_img = np.ones((200, 200, 3), dtype=np.uint8) * 80
    cv2.circle(bob_img, (70, 70), 30, (200, 100, 50), -1)
    _, bob_buf = cv2.imencode(".jpg", bob_img)
    bob_b64 = "data:image/jpeg;base64," + base64.b64encode(bob_buf.tobytes()).decode("utf-8")

    stranger_img = np.ones((200, 200, 3), dtype=np.uint8) * 20
    _, st_buf = cv2.imencode(".jpg", stranger_img)
    stranger_b64 = "data:image/jpeg;base64," + base64.b64encode(st_buf.tobytes()).decode("utf-8")

    orig_detect = face_service.detect_faces
    try:
        # Register Alice and Bob faces with single box detection
        face_service.detect_faces = lambda img: [(20, 20, 120, 120)]
        _set_role(client, "admin")
        client.post(f"/api/students/{s1['student_id']}/register-face", json={"image": alice_b64})
        client.post(f"/api/students/{s2['student_id']}/register-face", json={"image": bob_b64})
        _set_role(client, "faculty")

        # Start attendance session via frontend route
        resp = client.post("/actions/sessions/start", data={
            "course_id": course_id,
            "section": "All",
            "topic": "Graph Algorithms Lecture"
        }, follow_redirects=False)
        assert resp.status_code == 302
        session_id = resp.headers["Location"].split("/")[-1]

        # Branch 1: NO FACE DETECTED
        face_service.detect_faces = lambda img: []
        no_face_resp = client.post(f"/api/sessions/{session_id}/recognize", json={"image": alice_b64})
        assert no_face_resp.status_code == 200
        assert no_face_resp.get_json()["status"] == "no_face"

        # Branch 2: MULTIPLE FACES DETECTED
        face_service.detect_faces = lambda img: [(10, 10, 50, 50), (100, 100, 50, 50)]
        multi_resp = client.post(f"/api/sessions/{session_id}/recognize", json={"image": alice_b64})
        assert multi_resp.status_code == 200
        assert multi_resp.get_json()["status"] == "multiple_faces"

        # Restore single face detection
        face_service.detect_faces = lambda img: [(20, 20, 120, 120)]

        # Branch 3: UNRECOGNIZED / UNKNOWN FACE
        orig_extract = face_service.extract_embedding
        try:
            face_service.extract_embedding = lambda crop: np.zeros(576, dtype=np.float32)
            unrec_resp = client.post(f"/api/sessions/{session_id}/recognize", json={"image": stranger_b64})
            assert unrec_resp.status_code == 200
            assert unrec_resp.get_json()["status"] == "unrecognized"
        finally:
            face_service.extract_embedding = orig_extract

        # Branch 4: VALID RECOGNIZED ENROLLED STUDENT MARKED ONCE
        rec_resp = client.post(f"/api/sessions/{session_id}/recognize", json={"image": alice_b64})
        assert rec_resp.status_code == 200
        rec_data = rec_resp.get_json()
        assert rec_data["status"] == "marked"
        assert rec_data["student"]["student_id"] == s1["student_id"]

        # Verify SQLite attendance record
        records = AttendanceRecordModel.get_session_attendance(session_id, db_path=db_path)
        assert len(records) == 1
        assert records[0]["student_id"] == s1["student_id"]
        assert records[0]["status"] == "Present"

        # Branch 5: REPEATED PRESENTATION BLOCKED AS DUPLICATE
        dup_resp = client.post(f"/api/sessions/{session_id}/recognize", json={"image": alice_b64})
        assert dup_resp.status_code == 200
        assert dup_resp.get_json()["status"] == "already_marked"
        records_after = AttendanceRecordModel.get_session_attendance(session_id, db_path=db_path)
        assert len(records_after) == 1  # No duplicate record created

        # Branch 6: NON-ENROLLED RECOGNIZED STUDENT REJECTED
        bob_resp = client.post(f"/api/sessions/{session_id}/recognize", json={"image": bob_b64})
        assert bob_resp.status_code == 200
        assert bob_resp.get_json()["status"] == "not_enrolled"

        # Branch 7: CLOSE SESSION AND VERIFY REJECTION
        close_resp = client.post(f"/api/sessions/{session_id}/end")
        assert close_resp.status_code == 200

        post_close_resp = client.post(f"/api/sessions/{session_id}/recognize", json={"image": alice_b64})
        assert post_close_resp.status_code == 400
        assert post_close_resp.get_json()["status"] == "session_inactive"

        # Branch 8: NONEXISTENT SESSION REJECTION
        bad_sess_resp = client.post("/api/sessions/NONEXISTENT_SESSION_999/recognize", json={"image": alice_b64})
        assert bad_sess_resp.status_code == 404

    finally:
        face_service.detect_faces = orig_detect


def test_6_true_restart_persistence(tmp_path):
    """
    Step 6: True application restart persistence test.
    - Writes records and real embeddings to persistent SQLite & npz files.
    - Clears all in-memory singleton caches.
    - Instantiates fresh DataProvider and fresh FaceRecognitionService instances.
    - Verifies all courses, students, enrollments, sessions, attendance records,
      and biometric embeddings are fully restored from disk storage.
    """
    db_file = str(tmp_path / "restart_test.db")
    embeddings_file = str(tmp_path / "restart_embeddings.npz")

    init_db(db_file)
    fac_user = AuthService.create_user("fac_restart", "pass123", "faculty", db_path=db_file)
    conn = get_db_connection(db_file)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO faculty (faculty_id, user_id, name, email, department) VALUES ('FAC001', ?, 'Dr. Restart', 'r@c.edu', 'CSE');",
        (fac_user["id"],)
    )
    conn.commit()
    conn.close()

    # Pre-restart provider
    dp1 = DataProvider(db_path=db_file, embeddings_path=embeddings_file)
    st = dp1.create_student("229301088", "Restart Student", "restart@college.edu")
    cr = dp1.create_course("CS701", "Cloud Architecture", faculty_id="FAC001")
    EnrollmentModel.enroll_student(cr["course_id"], st["student_id"], db_path=db_file)

    # Register face embedding and persist to disk
    dummy_img = np.ones((200, 200, 3), dtype=np.uint8) * 150
    _, buf = cv2.imencode(".jpg", dummy_img)
    dummy_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("utf-8")

    orig_detect = face_service.detect_faces
    try:
        face_service.detect_faces = lambda img: [(20, 20, 120, 120)]
        face_service.register_student_face(st["student_id"], dummy_b64)
        face_service.save_embeddings(embeddings_file)
        StudentModel.set_face_registered(st["student_id"], True, db_path=db_file)
    finally:
        face_service.detect_faces = orig_detect

    # Start and record attendance
    ok, _, session = AttendanceService.start_session(cr["course_id"], "FAC001", "Cloud Session", db_path=db_file)
    sess_id = session["session_id"]
    AttendanceService.record_attendance(sess_id, st["student_id"], method="Face Recognition", db_path=db_file)
    AttendanceService.close_session(sess_id, db_path=db_file)

    # =========================================================================
    # SIMULATE FULL PROCESS RESTART / MEMORY FLUSH
    # =========================================================================
    face_service.clear_registry()
    del dp1

    # Verify memory is cleared
    assert len(face_service.get_registered_student_ids()) == 0

    # Start fresh DataProvider pointing to the persisted files
    fresh_dp = DataProvider(db_path=db_file, embeddings_path=embeddings_file)

    # 1. Verify students persisted
    students = fresh_dp.get_all_students()
    assert len(students) == 1
    assert students[0]["roll_no"] == "229301088"
    assert students[0]["has_face"] is True

    # 2. Verify courses persisted
    courses = fresh_dp.get_all_courses()
    assert len(courses) == 1
    assert courses[0]["code"] == "CS701"

    # 3. Verify attendance records persisted
    records = AttendanceRecordModel.get_session_attendance(sess_id, db_path=db_file)
    assert len(records) == 1
    assert records[0]["student_id"] == st["student_id"]
    assert records[0]["status"] == "Present"

    # 4. Verify embeddings loaded from configured disk file
    fresh_fs = FaceRecognitionService()
    assert fresh_fs.load_embeddings(embeddings_file) is True
    assert st["student_id"] in fresh_fs.get_registered_student_ids()


def test_7_csv_export_multi_course_and_edge_cases(e2e_env):
    """
    Step 7: Complete CSV export coverage:
    - course_id=all with >= 2 courses and distinct attendance records (no omissions or duplicates).
    - Correct RFC 4180 headers and percentage formatting (X.X%).
    - Course with 0 attendance sessions.
    - Invalid course_id returns HTTP 404.
    - Proper CSV field escaping for special characters (commas, quotes in student names).
    """
    dp = e2e_env["data_provider"]
    db_path = e2e_env["db_path"]
    client = e2e_env["client"]

    # Create 2 distinct courses
    c1 = dp.create_course("CS801", "Compiler Design", faculty_id="FAC001")
    c2 = dp.create_course("CS802", "Distributed Systems", faculty_id="FAC001")

    # Create students with special characters in names to verify RFC 4180 CSV escaping
    s1 = dp.create_student("229301031", 'Smith, John "Jack"', "jack@college.edu")
    s2 = dp.create_student("229301032", "Patel, Priya", "priya@college.edu")

    # Enroll s1 in c1, s2 in c2
    EnrollmentModel.enroll_student(c1["course_id"], s1["student_id"], db_path=db_path)
    EnrollmentModel.enroll_student(c2["course_id"], s2["student_id"], db_path=db_path)

    # Create session and record attendance in c1
    ok, _, sess1 = AttendanceService.start_session(c1["course_id"], "FAC001", "Parser Session", db_path=db_path)
    AttendanceService.record_attendance(sess1["session_id"], s1["student_id"], db_path=db_path)
    AttendanceService.close_session(sess1["session_id"], db_path=db_path)

    # Create session in c2 but do NOT record s2 attendance (0% attendance)
    ok, _, sess2 = AttendanceService.start_session(c2["course_id"], "FAC001", "Consensus Session", db_path=db_path)
    AttendanceService.close_session(sess2["session_id"], db_path=db_path)

    # 1. Multi-course export: course_id=all
    all_resp = client.get("/api/reports/export-csv?course_id=all")
    assert all_resp.status_code == 200
    assert all_resp.mimetype == "text/csv"
    csv_text = all_resp.data.decode("utf-8")

    reader = list(csv.reader(io.StringIO(csv_text)))
    assert len(reader) >= 3  # Header + at least 2 students
    header = reader[0]
    expected_header = [
        'Roll Number',
        'Student Name',
        'Section',
        'Course Code',
        'Total Sessions',
        'Attended Sessions',
        'Attendance Percentage',
        'Eligibility Status'
    ]
    assert header == expected_header

    # Check rows (row[0] is Roll Number)
    rows_by_roll = {row[0]: row for row in reader[1:] if len(row) > 1}
    assert "229301031" in rows_by_roll
    assert "229301032" in rows_by_roll

    row1 = rows_by_roll["229301031"]
    assert row1[0] == "229301031"
    assert row1[1] == 'Smith, John "Jack"'  # CSV escaping handled properly by csv.reader
    assert row1[3] == "CS801"
    assert row1[4] == "1"
    assert row1[5] == "1"
    assert row1[6] == "100.0%"
    assert row1[7] == "Eligible"

    row2 = rows_by_roll["229301032"]
    assert row2[0] == "229301032"
    assert row2[1] == "Patel, Priya"
    assert row2[3] == "CS802"
    assert row2[4] == "1"
    assert row2[5] == "0"
    assert row2[6] == "0.0%"
    assert row2[7] == "Low Attendance Warning"

    # 2. Single course export: c1
    c1_resp = client.get(f"/api/reports/export-csv?course_id={c1['course_id']}")
    assert c1_resp.status_code == 200
    c1_reader = list(csv.reader(io.StringIO(c1_resp.data.decode("utf-8"))))
    assert len(c1_reader) == 2  # Header + 1 student
    assert c1_reader[1][0] == "229301031"

    # 3. Course with 0 sessions
    c3 = dp.create_course("CS803", "Empty Sessions Course", faculty_id="FAC001")
    s3 = dp.create_student("229301033", "Empty Student", "empty@college.edu")
    EnrollmentModel.enroll_student(c3["course_id"], s3["student_id"], db_path=db_path)
    c3_resp = client.get(f"/api/reports/export-csv?course_id={c3['course_id']}")
    assert c3_resp.status_code == 200
    c3_reader = list(csv.reader(io.StringIO(c3_resp.data.decode("utf-8"))))
    assert len(c3_reader) == 2
    assert c3_reader[1][4] == "0"
    assert c3_reader[1][5] == "0"
    assert c3_reader[1][6] == "N/A"  # no sessions held yet: not a misleading 100%
    assert c3_reader[1][7] == "No sessions yet"

    # 4. Nonexistent course returns 404
    bad_resp = client.get("/api/reports/export-csv?course_id=INVALID_CRS_404")
    assert bad_resp.status_code == 404


def test_8_invalid_identifiers_produce_honest_errors(e2e_env):
    """Step 8: Nonexistent records return clear errors without fallback."""
    dp = e2e_env["data_provider"]
    client = e2e_env["client"]

    # Starting session with invalid course raises ValueError
    with pytest.raises(ValueError, match="does not exist"):
        dp.start_session("NONEXISTENT_COURSE_ID", faculty_id="FAC001")

    # CSV export for nonexistent course returns 404
    resp = client.get("/api/reports/export-csv?course_id=NONEXISTENT_COURSE")
    assert resp.status_code == 404
