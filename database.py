"""
database.py - Database initialization, connection management, and schema setup
for Smart Attendance System (CSE3132).
Technology: SQLite3 with foreign key enforcement and row-factory support.
"""

import os
import sqlite3
from contextlib import contextmanager

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), 'smart_attendance.db')


def get_db_connection(db_path=None):
    """
    Creates and returns a SQLite connection with foreign keys enabled
    and row factory set to sqlite3.Row for dict-like access.
    """
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db_cursor(db_path=None, commit=True):
    """
    Context manager for database transactions.
    Automatically commits on exit, or rolls back on exception.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        yield cursor
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path=None):
    """
    Creates all required tables for the Smart Attendance System MVP.
    Schema matches UML Class Diagram & System SRS requirements:
    - users (Auth & Roles)
    - faculty (Faculty members)
    - students (Registered students)
    - courses (Course catalog)
    - enrollments (Course-Student mapping)
    - class_sessions (Course attendance sessions)
    - attendance_records (Actual attendance records with duplicate prevention)
    """
    schema_sql = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin', 'faculty', 'student')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS faculty (
        faculty_id TEXT PRIMARY KEY,
        user_id INTEGER UNIQUE,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        department TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS students (
        student_id TEXT PRIMARY KEY,
        roll_number TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        program TEXT NOT NULL,
        semester INTEGER NOT NULL,
        face_registered INTEGER DEFAULT 0 CHECK(face_registered IN (0, 1)),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS courses (
        course_id TEXT PRIMARY KEY,
        course_code TEXT UNIQUE NOT NULL,
        course_name TEXT NOT NULL,
        credits INTEGER DEFAULT 3,
        faculty_id TEXT NOT NULL,
        semester INTEGER NOT NULL,
        academic_year TEXT DEFAULT '2026-2027',
        FOREIGN KEY (faculty_id) REFERENCES faculty(faculty_id) ON DELETE RESTRICT
    );

    CREATE TABLE IF NOT EXISTS enrollments (
        enrollment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id TEXT NOT NULL,
        student_id TEXT NOT NULL,
        enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE,
        FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
        UNIQUE(course_id, student_id)
    );

    CREATE TABLE IF NOT EXISTS class_sessions (
        session_id TEXT PRIMARY KEY,
        course_id TEXT NOT NULL,
        faculty_id TEXT NOT NULL,
        date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT,
        status TEXT NOT NULL DEFAULT 'Active' CHECK(status IN ('Active', 'Completed', 'Cancelled')),
        room TEXT DEFAULT 'Lab 204, Academic Block 3',
        topic TEXT,
        FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE RESTRICT,
        FOREIGN KEY (faculty_id) REFERENCES faculty(faculty_id) ON DELETE RESTRICT
    );

    CREATE TABLE IF NOT EXISTS attendance_records (
        attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        student_id TEXT NOT NULL,
        course_id TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT NOT NULL DEFAULT 'Present' CHECK(status IN ('Present', 'Absent', 'Late')),
        marking_method TEXT NOT NULL DEFAULT 'Face Recognition' CHECK(marking_method IN ('Face Recognition', 'Manual Override', 'Simulated Scanner')),
        confidence_score REAL,
        verified_by TEXT DEFAULT 'Face Recognition System',
        FOREIGN KEY (session_id) REFERENCES class_sessions(session_id) ON DELETE CASCADE,
        FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
        FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE,
        UNIQUE(session_id, student_id)
    );

    CREATE INDEX IF NOT EXISTS idx_attendance_session ON attendance_records(session_id);
    CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance_records(student_id);
    CREATE INDEX IF NOT EXISTS idx_attendance_course ON attendance_records(course_id);
    CREATE INDEX IF NOT EXISTS idx_sessions_course ON class_sessions(course_id);
    """

    with get_db_cursor(db_path) as cursor:
        cursor.executescript(schema_sql)


def seed_initial_data(db_path=None):
    """
    Seeds initial realistic data for Manipal University Jaipur CSE3132 lab:
    - 1 Admin user, 2 Faculty users
    - 8 Students (including project team members)
    - 4 Core Courses (CSE3132, CSE3101, CSE3103, CSE3105)
    - Course enrollments
    """
    from werkzeug.security import generate_password_hash

    with get_db_cursor(db_path) as cursor:
        # Check if already seeded
        cursor.execute("SELECT COUNT(*) AS count FROM courses;")
        if cursor.fetchone()['count'] > 0:
            return  # Already seeded

        # 1. Users
        users = [
            ('admin', generate_password_hash('admin123'), 'admin'),
            ('rajesh.kumar', generate_password_hash('faculty123'), 'faculty'),
            ('meenakshi.s', generate_password_hash('faculty123'), 'faculty'),
        ]
        cursor.executemany(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?);",
            users
        )

        # 2. Faculty
        cursor.execute("SELECT id FROM users WHERE username = 'rajesh.kumar';")
        fac1_uid = cursor.fetchone()['id']
        cursor.execute("SELECT id FROM users WHERE username = 'meenakshi.s';")
        fac2_uid = cursor.fetchone()['id']

        faculties = [
            ('FAC001', fac1_uid, 'Dr. Rajesh Kumar', 'rajesh.kumar@jaipur.manipal.edu', 'Computer Science & Engineering'),
            ('FAC002', fac2_uid, 'Dr. Meenakshi Sharma', 'meenakshi.s@jaipur.manipal.edu', 'Computer Science & Engineering'),
        ]
        cursor.executemany(
            "INSERT INTO faculty (faculty_id, user_id, name, email, department) VALUES (?, ?, ?, ?, ?);",
            faculties
        )

        # 3. Courses
        courses = [
            ('CRS-CSE3132', 'CSE3132', 'Software Engineering Laboratory', 2, 'FAC001', 5, '2026-2027'),
            ('CRS-CSE3101', 'CSE3101', 'Operating Systems & System Programming', 4, 'FAC002', 5, '2026-2027'),
            ('CRS-CSE3103', 'CSE3103', 'Database Management Systems', 3, 'FAC001', 5, '2026-2027'),
            ('CRS-CSE3105', 'CSE3105', 'Computer Networks & Security', 4, 'FAC002', 5, '2026-2027'),
        ]
        cursor.executemany(
            "INSERT INTO courses (course_id, course_code, course_name, credits, faculty_id, semester, academic_year) VALUES (?, ?, ?, ?, ?, ?, ?);",
            courses
        )

        # 4. Students
        students = [
            ('STU001', '229301045', 'Bhoomi Saraf', 'bhoomi.229301045@muj.manipal.edu', 'B.Tech CSE', 5, 1),
            ('STU002', '229301088', 'Kanakpreet Kaur', 'kanakpreet.229301088@muj.manipal.edu', 'B.Tech CSE', 5, 1),
            ('STU003', '229301112', 'Apoorva Kala', 'apoorva.229301112@muj.manipal.edu', 'B.Tech CSE', 5, 1),
            ('STU004', '229301150', 'Aarav Sharma', 'aarav.229301150@muj.manipal.edu', 'B.Tech CSE', 5, 1),
            ('STU005', '229301198', 'Rohan Mehta', 'rohan.229301198@muj.manipal.edu', 'B.Tech CSE', 5, 1),
            ('STU006', '229301224', 'Priya Patel', 'priya.229301224@muj.manipal.edu', 'B.Tech CSE', 5, 1),
            ('STU007', '229301275', 'Kabir Verma', 'kabir.229301275@muj.manipal.edu', 'B.Tech CSE', 5, 0),
            ('STU008', '229301310', 'Ananya Deshmukh', 'ananya.229301310@muj.manipal.edu', 'B.Tech CSE', 5, 1),
        ]
        cursor.executemany(
            "INSERT INTO students (student_id, roll_number, name, email, program, semester, face_registered) VALUES (?, ?, ?, ?, ?, ?, ?);",
            students
        )

        # 5. Enrollments for CSE3132 (Software Engineering Lab)
        for s in students:
            cursor.execute(
                "INSERT INTO enrollments (course_id, student_id) VALUES (?, ?);",
                ('CRS-CSE3132', s[0])
            )

        # Enrollments for CSE3101 (First 5 students)
        for s in students[:5]:
            cursor.execute(
                "INSERT INTO enrollments (course_id, student_id) VALUES (?, ?);",
                ('CRS-CSE3101', s[0])
            )
