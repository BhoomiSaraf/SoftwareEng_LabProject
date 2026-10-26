"""
models.py - Entity data models and database query operations for Smart Attendance System.
Encapsulates CRUD queries for Students, Faculty, Courses, Enrollments, Sessions, and Attendance.
"""

from typing import List, Optional, Dict, Any
from database import get_db_cursor


class StudentModel:
    @staticmethod
    def get_all(db_path=None) -> List[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute("SELECT * FROM students ORDER BY roll_number ASC;")
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_by_id(student_id: str, db_path=None) -> Optional[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute("SELECT * FROM students WHERE student_id = ?;", (student_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_roll(roll_number: str, db_path=None) -> Optional[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute("SELECT * FROM students WHERE roll_number = ?;", (roll_number,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def create(student_id: str, roll_number: str, name: str, email: str, program: str, semester: int, face_registered: int = 0, db_path=None) -> Dict[str, Any]:
        with get_db_cursor(db_path) as cursor:
            cursor.execute(
                """
                INSERT INTO students (student_id, roll_number, name, email, program, semester, face_registered)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (student_id, roll_number, name, email, program, semester, face_registered)
            )
        return StudentModel.get_by_id(student_id, db_path)

    @staticmethod
    def set_face_registered(student_id: str, face_registered: bool = True, db_path=None) -> bool:
        with get_db_cursor(db_path) as cursor:
            cursor.execute(
                "UPDATE students SET face_registered = ? WHERE student_id = ?;",
                (1 if face_registered else 0, student_id)
            )
            return cursor.rowcount > 0


class FacultyModel:
    @staticmethod
    def get_all(db_path=None) -> List[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute("SELECT * FROM faculty ORDER BY name ASC;")
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_by_id(faculty_id: str, db_path=None) -> Optional[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute("SELECT * FROM faculty WHERE faculty_id = ?;", (faculty_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


class CourseModel:
    @staticmethod
    def get_all(db_path=None) -> List[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                """
                SELECT c.*, f.name AS faculty_name, f.email AS faculty_email
                FROM courses c
                JOIN faculty f ON c.faculty_id = f.faculty_id
                ORDER BY c.course_code ASC;
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_by_id(course_id: str, db_path=None) -> Optional[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                """
                SELECT c.*, f.name AS faculty_name, f.email AS faculty_email
                FROM courses c
                JOIN faculty f ON c.faculty_id = f.faculty_id
                WHERE c.course_id = ?;
                """,
                (course_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None


class EnrollmentModel:
    @staticmethod
    def enroll_student(course_id: str, student_id: str, db_path=None) -> bool:
        with get_db_cursor(db_path) as cursor:
            try:
                cursor.execute(
                    "INSERT INTO enrollments (course_id, student_id) VALUES (?, ?);",
                    (course_id, student_id)
                )
                return True
            except Exception:
                return False

    @staticmethod
    def is_enrolled(course_id: str, student_id: str, db_path=None) -> bool:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                "SELECT 1 FROM enrollments WHERE course_id = ? AND student_id = ?;",
                (course_id, student_id)
            )
            return cursor.fetchone() is not None

    @staticmethod
    def get_enrolled_students(course_id: str, db_path=None) -> List[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                """
                SELECT s.*, e.enrolled_at
                FROM enrollments e
                JOIN students s ON e.student_id = s.student_id
                WHERE e.course_id = ?
                ORDER BY s.roll_number ASC;
                """,
                (course_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_student_courses(student_id: str, db_path=None) -> List[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                """
                SELECT c.*, f.name AS faculty_name
                FROM enrollments e
                JOIN courses c ON e.course_id = c.course_id
                JOIN faculty f ON c.faculty_id = f.faculty_id
                WHERE e.student_id = ?;
                """,
                (student_id,)
            )
            return [dict(row) for row in cursor.fetchall()]


class ClassSessionModel:
    @staticmethod
    def create(session_id: str, course_id: str, faculty_id: str, date: str, start_time: str, room: str = None, topic: str = None, db_path=None) -> Dict[str, Any]:
        with get_db_cursor(db_path) as cursor:
            cursor.execute(
                """
                INSERT INTO class_sessions (session_id, course_id, faculty_id, date, start_time, status, room, topic)
                VALUES (?, ?, ?, ?, ?, 'Active', ?, ?);
                """,
                (session_id, course_id, faculty_id, date, start_time, room, topic)
            )
        return ClassSessionModel.get_by_id(session_id, db_path)

    @staticmethod
    def get_by_id(session_id: str, db_path=None) -> Optional[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                """
                SELECT s.*, c.course_name, c.course_code, f.name AS faculty_name
                FROM class_sessions s
                JOIN courses c ON s.course_id = c.course_id
                JOIN faculty f ON s.faculty_id = f.faculty_id
                WHERE s.session_id = ?;
                """,
                (session_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_active_session_for_course(course_id: str, db_path=None) -> Optional[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                """
                SELECT * FROM class_sessions
                WHERE course_id = ? AND status = 'Active'
                ORDER BY date DESC, start_time DESC
                LIMIT 1;
                """,
                (course_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def close_session(session_id: str, end_time: str, db_path=None) -> bool:
        with get_db_cursor(db_path) as cursor:
            cursor.execute(
                "UPDATE class_sessions SET status = 'Completed', end_time = ? WHERE session_id = ? AND status = 'Active';",
                (end_time, session_id)
            )
            return cursor.rowcount > 0

    @staticmethod
    def list_by_course(course_id: str, db_path=None) -> List[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                """
                SELECT s.*, 
                       (SELECT COUNT(*) FROM attendance_records a WHERE a.session_id = s.session_id AND a.status = 'Present') AS present_count
                FROM class_sessions s
                WHERE s.course_id = ?
                ORDER BY s.date DESC, s.start_time DESC;
                """,
                (course_id,)
            )
            return [dict(row) for row in cursor.fetchall()]


class AttendanceRecordModel:
    @staticmethod
    def record_attendance(session_id: str, student_id: str, course_id: str, status: str = 'Present', method: str = 'Face Recognition', confidence_score: float = None, db_path=None) -> Dict[str, Any]:
        with get_db_cursor(db_path) as cursor:
            cursor.execute(
                """
                INSERT INTO attendance_records (session_id, student_id, course_id, status, marking_method, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (session_id, student_id, course_id, status, method, confidence_score)
            )
            rec_id = cursor.lastrowid
            cursor.execute("SELECT * FROM attendance_records WHERE attendance_id = ?;", (rec_id,))
            return dict(cursor.fetchone())

    @staticmethod
    def check_existing(session_id: str, student_id: str, db_path=None) -> Optional[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                "SELECT * FROM attendance_records WHERE session_id = ? AND student_id = ?;",
                (session_id, student_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_session_attendance(session_id: str, db_path=None) -> List[Dict[str, Any]]:
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                """
                SELECT a.*, s.roll_number, s.name AS student_name, s.email AS student_email
                FROM attendance_records a
                JOIN students s ON a.student_id = s.student_id
                WHERE a.session_id = ?
                ORDER BY a.timestamp ASC;
                """,
                (session_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def update_status(attendance_id: int, new_status: str, verified_by: str = 'Faculty Manual Override', db_path=None) -> bool:
        with get_db_cursor(db_path) as cursor:
            cursor.execute(
                """
                UPDATE attendance_records 
                SET status = ?, marking_method = 'Manual Override', verified_by = ?
                WHERE attendance_id = ?;
                """,
                (new_status, verified_by, attendance_id)
            )
            return cursor.rowcount > 0
