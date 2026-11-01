"""
data_provider.py - SQLite-backed Data Provider for Smart Attendance System
Integrates the presentation tier directly with SQLite (smart_attendance.db)
and manages students, courses, enrollments, and live attendance sessions.
"""

import os
import sqlite3
import datetime
from typing import List, Dict, Any, Optional
import database
from face_recognition_service import face_service

DB_PATH = database.DEFAULT_DB_PATH
EMBEDDINGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
EMBEDDINGS_FILE = os.path.join(EMBEDDINGS_DIR, 'embeddings.npz')


class DataProvider:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DB_PATH
        self._init_database()
        self._load_face_embeddings()

    def _init_database(self):
        """Ensure SQLite schema is initialized and base seed data is populated."""
        database.init_db(self.db_path)

        # Check if students exist in SQLite database
        conn = database.get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS count FROM students;")
        count = cursor.fetchone()['count']

        if count == 0:
            # Seed base students (matching course CSE3132 / CS301 roster)
            initial_students = [
                ('STU001', '21BCE001', 'Aarav Sharma', 'aarav.s@college.edu', 'B.Tech CSE', 5, 1),
                ('STU002', '21BCE002', 'Aditi Patel', 'aditi.p@college.edu', 'B.Tech CSE', 5, 1),
                ('STU003', '21BCE003', 'Alex Morgan', 'alex.m@college.edu', 'B.Tech CSE', 5, 1),
                ('STU004', '21BCE004', 'Bhoomi Saraf', 'bhoomi.s@college.edu', 'B.Tech CSE', 5, 1),
                ('STU005', '21BCE005', 'Chirag Dave', 'chirag.d@college.edu', 'B.Tech CSE', 5, 0),
                ('STU006', '21BCE006', 'Divya Nair', 'divya.n@college.edu', 'B.Tech CSE', 5, 1),
            ]
            cursor.executemany(
                """
                INSERT OR IGNORE INTO students (student_id, roll_number, name, email, program, semester, face_registered)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                initial_students
            )

            # Seed base courses if needed (development/testing environments only)
            cursor.execute("SELECT COUNT(*) AS count FROM courses;")
            course_count = cursor.fetchone()['count']
            from config import Config
            if course_count == 0 and not Config.IS_PRODUCTION:
                from werkzeug.security import generate_password_hash
                # Seed faculty user first to satisfy foreign key constraint
                cursor.execute(
                    "INSERT OR IGNORE INTO users (id, username, password_hash, role) VALUES (?, ?, ?, ?);",
                    (1, 'faculty@college.edu', generate_password_hash('faculty123'), 'faculty')
                )
                cursor.execute(
                    "INSERT OR IGNORE INTO faculty (faculty_id, user_id, name, email, department) VALUES (?, ?, ?, ?, ?);",
                    ('FAC001', 1, 'Dr. Alan Turing', 'alan.turing@college.edu', 'Computer Science & Engineering')
                )
                initial_courses = [
                    ('CS301', 'CS301', 'Software Engineering Lab', 2, 'FAC001', 5, '2026-2027'),
                    ('CS304', 'CS304', 'Machine Learning', 3, 'FAC001', 5, '2026-2027'),
                    ('CS306', 'CS306', 'Operating Systems', 3, 'FAC001', 5, '2026-2027'),
                ]
                cursor.executemany(
                    """
                    INSERT OR IGNORE INTO courses (course_id, course_code, course_name, credits, faculty_id, semester, academic_year)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    initial_courses
                )

            # Enroll all initial students into CS301
            for s in initial_students:
                cursor.execute(
                    "INSERT OR IGNORE INTO enrollments (course_id, student_id) VALUES (?, ?);",
                    ('CS301', s[0])
                )

            # Enroll students 1, 2, 6 into CS304
            for sid in ['STU001', 'STU002', 'STU006']:
                cursor.execute(
                    "INSERT OR IGNORE INTO enrollments (course_id, student_id) VALUES (?, ?);",
                    ('CS304', sid)
                )

            # Enroll students 3, 4 into CS306
            for sid in ['STU003', 'STU004']:
                cursor.execute(
                    "INSERT OR IGNORE INTO enrollments (course_id, student_id) VALUES (?, ?);",
                    ('CS306', sid)
                )

            conn.commit()

        # Ensure session 101 exists in SQLite database with persisted attendance
        cursor.execute("SELECT COUNT(*) AS count FROM class_sessions WHERE session_id = '101';")
        if cursor.fetchone()['count'] == 0:
            cursor.execute("SELECT 1 FROM courses WHERE course_id = 'CS301';")
            if cursor.fetchone():
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO class_sessions (session_id, course_id, faculty_id, date, start_time, status, room, topic)
                    VALUES ('101', 'CS301', 'FAC001', '2026-10-27', '09:00:00', 'Active', 'Lab 204, Academic Block 3', 'Software Engineering Lab');
                    """
                )
                initial_marked = [
                    ('101', 'STU001', 'CS301', '09:02:14 AM', 'Present', 'Face Recognition', 0.95),
                    ('101', 'STU002', 'CS301', '09:03:05 AM', 'Present', 'Face Recognition', 0.92),
                    ('101', 'STU003', 'CS301', '09:04:12 AM', 'Present', 'Face Recognition', 0.89),
                ]
                cursor.executemany(
                    """
                    INSERT OR IGNORE INTO attendance_records 
                    (session_id, student_id, course_id, timestamp, status, marking_method, confidence_score, verified_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'Face Recognition System');
                    """,
                    initial_marked
                )
                conn.commit()

        conn.close()

    def _load_face_embeddings(self):
        """Auto-load any persisted embeddings from disk into face_service."""
        if os.path.exists(EMBEDDINGS_FILE):
            face_service.load_embeddings(EMBEDDINGS_FILE)

    # -------------------------------------------------------------------------
    # Student Operations
    # -------------------------------------------------------------------------

    def get_all_students(self) -> List[Dict[str, Any]]:
        """Return all students from SQLite database with current biometric status."""
        conn = database.get_db_connection(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM students ORDER BY student_id ASC;")
        rows = cursor.fetchall()

        # Query enrollments
        cursor.execute("""
            SELECT e.student_id, c.course_code 
            FROM enrollments e 
            JOIN courses c ON e.course_id = c.course_id OR e.course_id = c.course_code;
        """)
        enrollment_rows = cursor.fetchall()
        course_map = {}
        for er in enrollment_rows:
            sid = er['student_id']
            code = er['course_code']
            if sid not in course_map:
                course_map[sid] = []
            if code not in course_map[sid]:
                course_map[sid].append(code)

        conn.close()

        registered_face_ids = set(face_service.get_registered_student_ids())

        results = []
        for i, row in enumerate(rows, start=1):
            sid_str = row['student_id']
            roll = row['roll_number']
            name = row['name']

            numeric_id = i
            if sid_str.startswith('STU') and sid_str[3:].isdigit():
                numeric_id = int(sid_str[3:])

            has_face_in_service = (
                str(numeric_id) in registered_face_ids or
                sid_str in registered_face_ids or
                roll in registered_face_ids
            )

            has_face = bool(row['face_registered'] or has_face_in_service)
            sample_count = len(face_service._registered_embeddings.get(str(numeric_id), []))
            if sample_count == 0:
                sample_count = len(face_service._registered_embeddings.get(roll, []))
            if sample_count == 0 and has_face:
                sample_count = 1

            courses = course_map.get(sid_str, [])

            results.append({
                'id': numeric_id,
                'student_id': sid_str,
                'roll_no': roll,
                'name': name,
                'email': row['email'],
                'has_face': has_face,
                'face_samples_count': sample_count,
                'course_codes': courses
            })

        return results

    def create_student(self, roll_no: str, name: str, email: str, program: str = "B.Tech CSE", semester: int = 5) -> Dict[str, Any]:
        """Insert a newly registered student into SQLite database."""
        roll_no = roll_no.strip()
        name = name.strip()
        email = email.strip()

        conn = database.get_db_connection(self.db_path)
        cursor = conn.cursor()

        # Check if student already exists by roll_number or email
        cursor.execute("SELECT * FROM students WHERE roll_number = ? OR email = ?;", (roll_no, email))
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return self.get_student_by_roll(roll_no)

        # Generate next unique ID
        cursor.execute("SELECT student_id FROM students WHERE student_id LIKE 'STU%';")
        existing_ids = [r['student_id'] for r in cursor.fetchall()]
        max_num = 0
        for eid in existing_ids:
            num_part = eid[3:]
            if num_part.isdigit() and int(num_part) > max_num:
                max_num = int(num_part)
        next_num = max_num + 1
        new_sid = f"STU{next_num:03d}"

        # Insert student
        cursor.execute(
            """
            INSERT INTO students (student_id, roll_number, name, email, program, semester, face_registered)
            VALUES (?, ?, ?, ?, ?, ?, 0);
            """,
            (new_sid, roll_no, name, email, program, semester)
        )

        # Automatically enroll into default course if it exists
        cursor.execute("SELECT course_id FROM courses WHERE course_id = 'CS301' OR course_id LIKE 'CRS-%' LIMIT 1;")
        default_course = cursor.fetchone()
        if default_course:
            cursor.execute(
                "INSERT OR IGNORE INTO enrollments (course_id, student_id) VALUES (?, ?);",
                (default_course['course_id'], new_sid)
            )

        conn.commit()
        conn.close()

        return {
            'id': next_num,
            'student_id': new_sid,
            'roll_no': roll_no,
            'name': name,
            'email': email,
            'has_face': False,
            'face_samples_count': 0,
            'course_codes': [default_course['course_id']] if default_course else []
        }

    def get_student_by_id(self, student_id: int) -> Optional[Dict[str, Any]]:
        """Look up student by integer ID or string key."""
        all_students = self.get_all_students()
        return next((s for s in all_students if s['id'] == student_id or s['student_id'] == f"STU{student_id:03d}"), None)

    def get_student_by_roll(self, roll_no: str) -> Optional[Dict[str, Any]]:
        """Look up student by roll number."""
        all_students = self.get_all_students()
        return next((s for s in all_students if s['roll_no'].lower() == roll_no.lower()), None)

    def set_student_face_registered(self, student_id_or_roll: str, face_registered: bool = True):
        """Mark face biometrics as registered in SQLite."""
        conn = database.get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE students 
            SET face_registered = ? 
            WHERE student_id = ? OR roll_number = ? OR student_id = ?;
            """,
            (
                1 if face_registered else 0,
                str(student_id_or_roll),
                str(student_id_or_roll),
                f"STU{int(student_id_or_roll):03d}" if str(student_id_or_roll).isdigit() else str(student_id_or_roll)
            )
        )
        conn.commit()
        conn.close()

    # -------------------------------------------------------------------------
    # Course & Session Operations
    # -------------------------------------------------------------------------

    def get_all_courses(self) -> List[Dict[str, Any]]:
        """Return course catalog queried live from SQLite."""
        conn = database.get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT c.*, f.name AS faculty_name,
                   (SELECT COUNT(*) FROM enrollments e WHERE e.course_id = c.course_id) AS enrolled_count,
                   (SELECT COUNT(*) FROM class_sessions s WHERE s.course_id = c.course_id) AS sessions_count
            FROM courses c
            LEFT JOIN faculty f ON c.faculty_id = f.faculty_id
            ORDER BY c.course_code ASC;
            """
        )
        rows = cursor.fetchall()
        conn.close()

        results = []
        for i, r in enumerate(rows, start=1):
            results.append({
                'id': i,
                'course_id': r['course_id'],
                'code': r['course_code'],
                'name': r['course_name'],
                'faculty_name': r['faculty_name'] or 'Dr. Alan Turing',
                'enrolled_count': r['enrolled_count'],
                'sessions_count': r['sessions_count'],
                'description': f"Credits: {r['credits']} | Semester {r['semester']} ({r['academic_year']})"
            })
        return results

    def create_course(self, code: str, name: str, description: str = "") -> Optional[Dict[str, Any]]:
        """Insert a newly created course into SQLite database."""
        code = code.strip().upper()
        name = name.strip()
        conn = database.get_db_connection(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT faculty_id FROM faculty LIMIT 1;")
        fac_row = cursor.fetchone()
        faculty_id = fac_row['faculty_id'] if fac_row else 'FAC001'

        course_id = f"CRS-{code}"
        try:
            cursor.execute(
                """
                INSERT INTO courses (course_id, course_code, course_name, credits, faculty_id, semester, academic_year)
                VALUES (?, ?, ?, 3, ?, 5, '2026-2027');
                """,
                (course_id, code, name, faculty_id)
            )
            conn.commit()
            conn.close()
            courses = self.get_all_courses()
            return next((c for c in courses if c['code'] == code), None)
        except Exception:
            conn.close()
            return None

    def start_session(self, course_id: Any, topic: str = "Regular Lecture") -> str:
        """Start a new active attendance session in SQLite via AttendanceService."""
        conn = database.get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM courses WHERE course_id = ? OR course_code = ?;", (str(course_id), str(course_id)))
        course = cursor.fetchone()
        if not course:
            courses = self.get_all_courses()
            if str(course_id).isdigit():
                idx = int(course_id)
                if 1 <= idx <= len(courses):
                    c_entry = courses[idx - 1]
                    cursor.execute("SELECT * FROM courses WHERE course_id = ?;", (c_entry['course_id'],))
                    course = cursor.fetchone()

        if not course:
            cursor.execute("SELECT * FROM courses LIMIT 1;")
            course = cursor.fetchone()

        if not course:
            conn.close()
            raise RuntimeError("No courses exist to start an attendance session.")

        actual_course_id = course['course_id']
        faculty_id = course['faculty_id']
        conn.close()

        from attendance_service import AttendanceService
        success, msg, session = AttendanceService.start_session(
            course_id=actual_course_id,
            faculty_id=faculty_id,
            topic=topic or "Regular Lecture",
            db_path=self.db_path
        )
        if success and session:
            return session['session_id']
        raise RuntimeError(msg)

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Calculate real dashboard metrics from SQLite database."""
        conn = database.get_db_connection(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) AS count FROM class_sessions WHERE status = 'Active';")
        active_sessions_count = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) AS count FROM students;")
        total_students_count = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) AS count FROM courses;")
        total_courses_count = cursor.fetchone()['count']

        # Calculate average attendance rate across all sessions
        cursor.execute(
            """
            SELECT s.session_id, s.course_id,
                   (SELECT COUNT(*) FROM attendance_records a WHERE a.session_id = s.session_id AND a.status = 'Present') AS present_count,
                   (SELECT COUNT(*) FROM enrollments e WHERE e.course_id = s.course_id) AS enrolled_count
            FROM class_sessions s;
            """
        )
        session_rows = cursor.fetchall()
        total_present = sum(r['present_count'] for r in session_rows)
        total_expected = sum(r['enrolled_count'] for r in session_rows)

        if total_expected > 0:
            avg_attendance = f"{round((total_present / total_expected) * 100, 1)}%"
        else:
            avg_attendance = "0.0%"

        # Query recent sessions
        cursor.execute(
            """
            SELECT s.session_id, s.course_id, s.date, s.start_time, s.status,
                   c.course_code, c.course_name,
                   (SELECT COUNT(*) FROM attendance_records a WHERE a.session_id = s.session_id AND a.status = 'Present') AS present_count,
                   (SELECT COUNT(*) FROM enrollments e WHERE e.course_id = s.course_id) AS total_enrolled
            FROM class_sessions s
            LEFT JOIN courses c ON s.course_id = c.course_id
            ORDER BY s.date DESC, s.start_time DESC
            LIMIT 10;
            """
        )
        recent_rows = cursor.fetchall()
        conn.close()

        recent_sessions = []
        for r in recent_rows:
            enrolled = r['total_enrolled'] or 0
            present = r['present_count'] or 0
            pct = int(round((present / max(1, enrolled)) * 100)) if enrolled > 0 else 0
            recent_sessions.append({
                'id': r['session_id'],
                'course_code': r['course_code'] or r['course_id'],
                'course_name': r['course_name'] or 'Curriculum Session',
                'date': r['date'],
                'start_time': r['start_time'],
                'status': r['status'].upper(),
                'present_count': present,
                'total_enrolled': enrolled,
                'attendance_percentage': pct
            })

        courses = self.get_all_courses()

        stats = {
            'active_sessions': active_sessions_count,
            'total_students': total_students_count,
            'total_courses': total_courses_count,
            'avg_attendance': avg_attendance
        }

        return {
            'stats': stats,
            'recent_sessions': recent_sessions,
            'courses': courses
        }

    def get_session_details(self, session_id: Any) -> Optional[Dict[str, Any]]:
        """Return session details including dynamic enrolled and present counts from SQLite."""
        from models import ClassSessionModel
        session = ClassSessionModel.get_by_id(str(session_id), self.db_path)
        if not session:
            return None

        enrolled = self.get_enrolled_students_for_session(session_id)
        records = self.get_attendance_records(session_id)
        present_count = len(records)
        total_enrolled = max(1, len(enrolled))
        percentage = int(round((present_count / total_enrolled) * 100)) if total_enrolled > 0 else 0

        return {
            'id': session['session_id'],
            'course_id': session['course_id'],
            'faculty_id': session.get('faculty_id'),
            'course_code': session.get('course_code') or session['course_id'],
            'course_name': session.get('course_name') or 'Attendance Session',
            'faculty_name': session.get('faculty_name') or 'Dr. Alan Turing',
            'start_time': session.get('start_time') or '09:00:00 AM',
            'status': session['status'].upper(),
            'total_enrolled': len(enrolled),
            'present_count': present_count,
            'attendance_percentage': percentage
        }

    def get_enrolled_students_for_session(self, session_id: Any) -> List[Dict[str, Any]]:
        """Return all students enrolled in the active course session from SQLite."""
        conn = database.get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.*, e.enrolled_at
            FROM class_sessions cs
            JOIN enrollments e ON cs.course_id = e.course_id
            JOIN students s ON e.student_id = s.student_id
            WHERE cs.session_id = ?
            ORDER BY s.roll_number ASC;
            """,
            (str(session_id),)
        )
        rows = cursor.fetchall()
        conn.close()

        results = []
        for i, r in enumerate(rows, start=1):
            sid_str = r['student_id']
            num_id = int(sid_str[3:]) if sid_str.startswith('STU') and sid_str[3:].isdigit() else i
            results.append({
                'id': num_id,
                'student_id': sid_str,
                'roll_no': r['roll_number'],
                'name': r['name'],
                'email': r['email']
            })
        return results

    def get_attendance_records(self, session_id: Any) -> List[Dict[str, Any]]:
        """Return current attendance records for session directly from SQLite."""
        conn = database.get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.*, s.name as student_name, s.roll_number as roll_no
            FROM attendance_records a
            JOIN students s ON a.student_id = s.student_id OR a.student_id = s.roll_number
            WHERE a.session_id = ?
            ORDER BY a.timestamp ASC;
            """,
            (str(session_id),)
        )
        db_records = cursor.fetchall()
        conn.close()

        return [
            {
                'student_id': r['student_id'],
                'roll_no': r['roll_no'],
                'student_name': r['student_name'],
                'timestamp': r['timestamp'],
                'method': r['marking_method']
            }
            for r in db_records
        ]

    def record_attendance(self, session_id: Any, student_id: Any, method: str = 'Face Recognition', confidence: Optional[float] = None) -> bool:
        """Persist attendance mark into SQLite database using authoritative AttendanceService."""
        student = self.get_student_by_id(student_id) if str(student_id).isdigit() else self.get_student_by_roll(str(student_id))
        if not student:
            return False

        from attendance_service import AttendanceService
        ok, msg, rec = AttendanceService.record_attendance(
            session_id=str(session_id),
            student_id=student['student_id'],
            method=method,
            confidence_score=confidence,
            db_path=self.db_path
        )
        return ok

    def get_reports_data(self, course_id: Optional[str] = None) -> Dict[str, Any]:
        """Aggregate authentic attendance analytics and session audits from SQLite."""
        conn = database.get_db_connection(self.db_path)
        cursor = conn.cursor()

        courses = self.get_all_courses()

        selected_course_row = None
        if course_id and str(course_id).lower() != 'all':
            for c in courses:
                if str(c['id']) == str(course_id) or str(c['course_id']) == str(course_id) or str(c['code']).lower() == str(course_id).lower():
                    selected_course_row = c
                    break

        student_reports = []
        session_logs = []

        target_courses = [selected_course_row] if selected_course_row else courses

        for c_entry in target_courses:
            cid = c_entry['course_id']
            from attendance_service import AttendanceService
            rep = AttendanceService.get_course_attendance_report(cid, self.db_path)
            if 'student_reports' in rep:
                for sr in rep['student_reports']:
                    student_reports.append({
                        'student_id': sr['student_id'],
                        'roll_no': sr['roll_number'],
                        'student_name': sr['name'],
                        'course_id': c_entry['id'],
                        'course_code': c_entry['code'],
                        'attended_sessions': sr['attended_sessions'],
                        'total_sessions': sr['total_sessions'],
                        'percentage': sr['attendance_percentage']
                    })

            cursor.execute(
                """
                SELECT s.*, c.course_code, c.course_name,
                       (SELECT COUNT(*) FROM attendance_records a WHERE a.session_id = s.session_id AND a.status = 'Present') AS present_count,
                       (SELECT COUNT(*) FROM enrollments e WHERE e.course_id = s.course_id) AS total_enrolled
                FROM class_sessions s
                JOIN courses c ON s.course_id = c.course_id
                WHERE s.course_id = ?
                ORDER BY s.date DESC, s.start_time DESC;
                """,
                (cid,)
            )
            for s_row in cursor.fetchall():
                enrolled = s_row['total_enrolled'] or 0
                present = s_row['present_count'] or 0
                pct = int(round((present / max(1, enrolled)) * 100)) if enrolled > 0 else 0
                session_logs.append({
                    'id': s_row['session_id'],
                    'course_code': s_row['course_code'],
                    'course_name': s_row['course_name'],
                    'date': s_row['date'],
                    'start_time': s_row['start_time'],
                    'present_count': present,
                    'total_enrolled': enrolled,
                    'attendance_percentage': pct,
                    'status': s_row['status'].upper()
                })

        conn.close()

        total_sessions = len(session_logs)
        total_students = len(student_reports)
        eligible_count = sum(1 for s in student_reports if s['percentage'] >= 75.0)
        warning_count = sum(1 for s in student_reports if s['percentage'] < 75.0)

        summary = {
            'total_sessions': total_sessions,
            'total_students': total_students,
            'eligible_count': eligible_count,
            'warning_count': warning_count
        }

        return {
            'courses': courses,
            'student_reports': student_reports,
            'session_logs': session_logs,
            'summary': summary
        }


# Global singleton instance
data_provider = DataProvider()

