"""
attendance_service.py - Centralized business logic and attendance engine for Smart Attendance System.
Enforces all Software Engineering Lab domain constraints:
1. Validates active session state (cannot mark before start or after closure).
2. Validates student existence and course enrollment eligibility.
3. Enforces strict duplicate prevention in the same session.
4. Generates academic reports and calculates attendance percentages with low-attendance warnings (< 75%).
5. Generates RFC 4180 compliant CSV export data.
6. Provides manual correction capabilities for faculty.
"""

import csv
import io
from datetime import datetime
from typing import Tuple, Dict, Any, List, Optional
from database import get_db_cursor
from models import (
    StudentModel,
    CourseModel,
    EnrollmentModel,
    ClassSessionModel,
    AttendanceRecordModel
)


class AttendanceService:
    @staticmethod
    def start_session(
        course_id: str,
        faculty_id: str,
        topic: Optional[str] = "Regular Lecture / Lab Evaluation",
        room: Optional[str] = "Lab 204, Academic Block 3",
        db_path=None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Starts a new attendance session for a given course and faculty.
        Automatically closes any existing Active session for that course to prevent orphan states.
        """
        # Validate course
        course = CourseModel.get_by_id(course_id, db_path)
        if not course:
            return False, f"Course '{course_id}' does not exist.", None

        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M:%S')

        # Close existing active session if any
        active_existing = ClassSessionModel.get_active_session_for_course(course_id, db_path)
        if active_existing:
            ClassSessionModel.close_session(active_existing['session_id'], time_str, db_path)

        # Generate unique session ID: SES-<COURSE>-YYYYMMDD-HHMMSS-microseconds
        session_id = f"SES-{course['course_code']}-{now.strftime('%Y%m%d%H%M%S%f')}"

        new_session = ClassSessionModel.create(
            session_id=session_id,
            course_id=course_id,
            faculty_id=faculty_id,
            date=date_str,
            start_time=time_str,
            room=room,
            topic=topic,
            db_path=db_path
        )

        return True, f"Attendance session {session_id} successfully started.", new_session

    @staticmethod
    def close_session(session_id: str, db_path=None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Closes an active attendance session, setting end_time and status to 'Completed'.
        After closure, no further attendance records can be accepted.
        """
        session = ClassSessionModel.get_by_id(session_id, db_path)
        if not session:
            return False, f"Session '{session_id}' not found.", None

        if session['status'] != 'Active':
            return False, f"Session '{session_id}' is already {session['status']}.", session

        now_time = datetime.now().strftime('%H:%M:%S')
        success = ClassSessionModel.close_session(session_id, now_time, db_path)
        if success:
            updated_session = ClassSessionModel.get_by_id(session_id, db_path)
            return True, f"Session {session_id} ended at {now_time}.", updated_session
        return False, "Failed to update session status.", None

    @staticmethod
    def record_attendance(
        session_id: str,
        student_id: str,
        method: str = 'Face Recognition',
        confidence_score: Optional[float] = None,
        db_path=None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        CENTRAL ATTENDANCE VALIDATION & RECORDING ENGINE.
        Used by the Face Recognition Module, Manual Overrides, and Scanner simulation.

        Verification Rules:
        1. Session must exist and be 'Active'.
        2. Student must exist in the system directory.
        3. Student must be enrolled in the course associated with the session.
        4. Student MUST NOT already have an attendance record for this session (Duplicate Prevention).
        """
        # Rule 1: Validate session status
        session = ClassSessionModel.get_by_id(session_id, db_path)
        if not session:
            return False, f"Invalid session ID '{session_id}'.", None

        if session['status'] != 'Active':
            return (
                False,
                f"Attendance rejected: Session {session_id} is '{session['status']}'. Attendance can only be recorded during an Active session.",
                None
            )

        # Rule 2: Validate student
        student = StudentModel.get_by_id(student_id, db_path)
        if not student:
            # Also check if student_id was provided as roll_number
            student = StudentModel.get_by_roll(student_id, db_path)
            if not student:
                return False, f"Student '{student_id}' is not registered in the system.", None

        actual_student_id = student['student_id']

        # Rule 3: Validate enrollment in this course
        if not EnrollmentModel.is_enrolled(session['course_id'], actual_student_id, db_path):
            return (
                False,
                f"Enrollment Error: {student['name']} ({student['roll_number']}) is not enrolled in course {session['course_code']}.",
                None
            )

        # Rule 4: Duplicate prevention check
        existing = AttendanceRecordModel.check_existing(session_id, actual_student_id, db_path)
        if existing:
            return (
                False,
                f"Duplicate attendance blocked: {student['name']} ({student['roll_number']}) is already marked '{existing['status']}' for session {session_id} (timestamp: {existing['timestamp']}).",
                existing
            )

        # Rule 5: Record attendance
        record = AttendanceRecordModel.record_attendance(
            session_id=session_id,
            student_id=actual_student_id,
            course_id=session['course_id'],
            status='Present',
            method=method,
            confidence_score=confidence_score,
            db_path=db_path
        )

        record_with_details = {
            **record,
            'student_name': student['name'],
            'roll_number': student['roll_number'],
            'course_code': session['course_code']
        }

        return True, f"Attendance marked: {student['name']} ({student['roll_number']}) is Present.", record_with_details

    @staticmethod
    def manual_override(
        attendance_id: int,
        new_status: str,
        faculty_name: str = "Faculty In-Charge",
        db_path=None
    ) -> Tuple[bool, str]:
        """
        Allows faculty to manually correct an attendance record (e.g. Present -> Absent or Late).
        """
        if new_status not in ('Present', 'Absent', 'Late'):
            return False, f"Invalid status: {new_status}. Must be 'Present', 'Absent', or 'Late'."

        success = AttendanceRecordModel.update_status(
            attendance_id=attendance_id,
            new_status=new_status,
            verified_by=f"Manual Override by {faculty_name}",
            db_path=db_path
        )
        if success:
            return True, f"Attendance record #{attendance_id} updated to '{new_status}'."
        return False, f"Record #{attendance_id} not found."

    @staticmethod
    def get_course_attendance_report(course_id: str, db_path=None) -> Dict[str, Any]:
        """
        Generates full academic attendance report for a course:
        - Total sessions held
        - For each enrolled student:
          * Sessions attended
          * Attendance percentage
          * Low attendance warning (< 75%)
        """
        course = CourseModel.get_by_id(course_id, db_path)
        if not course:
            return {"error": f"Course '{course_id}' not found."}

        # Get all completed or active sessions for this course
        with get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                "SELECT session_id, date, start_time, status FROM class_sessions WHERE course_id = ? ORDER BY date ASC;",
                (course_id,)
            )
            sessions = [dict(row) for row in cursor.fetchall()]

        total_sessions = len(sessions)
        session_ids = [s['session_id'] for s in sessions]

        # Get all enrolled students
        enrolled_students = EnrollmentModel.get_enrolled_students(course_id, db_path)

        student_reports = []
        for s in enrolled_students:
            student_id = s['student_id']
            # Count present / late records for this student in this course's sessions
            with get_db_cursor(db_path, commit=False) as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) as attended_count
                    FROM attendance_records
                    WHERE student_id = ? AND course_id = ? AND status IN ('Present', 'Late');
                    """,
                    (student_id, course_id)
                )
                attended_count = cursor.fetchone()['attended_count']

            # Calculate percentage
            percentage = round((attended_count / total_sessions * 100), 2) if total_sessions > 0 else 100.0
            is_low = percentage < 75.0

            student_reports.append({
                'student_id': student_id,
                'roll_number': s['roll_number'],
                'name': s['name'],
                'email': s['email'],
                'total_sessions': total_sessions,
                'attended_sessions': attended_count,
                'attendance_percentage': percentage,
                'low_attendance_warning': is_low,
            })

        return {
            'course': course,
            'total_sessions_held': total_sessions,
            'total_enrolled': len(enrolled_students),
            'student_reports': student_reports,
            'sessions': sessions
        }

    @staticmethod
    def generate_csv_report(course_id: str, db_path=None) -> str:
        """
        Generates an RFC 4180 CSV string of the course attendance report for academic records.
        """
        report_data = AttendanceService.get_course_attendance_report(course_id, db_path)
        if 'error' in report_data:
            return ""

        output = io.StringIO()
        writer = csv.writer(output)

        # Header info
        course = report_data['course']
        writer.writerow(["MANIPAL UNIVERSITY JAIPUR - SMART ATTENDANCE SYSTEM"])
        writer.writerow(["Course Code", course['course_code']])
        writer.writerow(["Course Name", course['course_name']])
        writer.writerow(["Faculty In-Charge", course['faculty_name']])
        writer.writerow(["Total Sessions Conducted", report_data['total_sessions_held']])
        writer.writerow([])

        # Table columns
        writer.writerow([
            "Student ID",
            "Roll Number",
            "Student Name",
            "Email",
            "Sessions Held",
            "Sessions Attended",
            "Attendance Percentage (%)",
            "Low Attendance (< 75%)"
        ])

        for row in report_data['student_reports']:
            writer.writerow([
                row['student_id'],
                row['roll_number'],
                row['name'],
                row['email'],
                row['total_sessions'],
                row['attended_sessions'],
                f"{row['attendance_percentage']}%",
                "YES - DEFICIENCY" if row['low_attendance_warning'] else "NO"
            ])

        return output.getvalue()
