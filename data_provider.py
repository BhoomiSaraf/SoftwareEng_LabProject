"""
data_provider.py - SQLite-backed Data Provider for Smart Attendance System.
Feeds the presentation tier from smart_attendance.db and the face-embedding registry.

Conventions
-----------
* Every student/course payload carries ``id`` equal to its canonical string key
  (``student_id`` / ``course_id``). There are no positional or numeric aliases.
* ``faculty_id`` arguments scope results to what that teacher is allowed to see
  (the courses and sections they are assigned to). ``None`` means unscoped (admin).
"""

import os
from typing import List, Dict, Any, Optional
import database
from config import Config
from face_recognition_service import face_service
from models import CourseSectionModel, EnrollmentModel

DB_PATH = database.DEFAULT_DB_PATH
EMBEDDINGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
EMBEDDINGS_FILE = os.path.join(EMBEDDINGS_DIR, 'embeddings.npz')

LOW_ATTENDANCE_THRESHOLD = 75.0


def _pct(present: int, total: int) -> int:
    return int(round(present / total * 100)) if total else 0


class DataProvider:
    def __init__(self, db_path: Optional[str] = None, embeddings_path: Optional[str] = None):
        self.db_path = db_path or DB_PATH
        self.embeddings_path = embeddings_path or getattr(Config, 'EMBEDDINGS_FILE', EMBEDDINGS_FILE)
        database.init_db(self.db_path)
        self._load_face_embeddings()

    def _load_face_embeddings(self):
        """Auto-load persisted embeddings from configured storage into face_service."""
        if self.embeddings_path and os.path.exists(self.embeddings_path):
            face_service.load_embeddings(self.embeddings_path)

    def _conn(self):
        return database.get_db_connection(self.db_path)

    # -------------------------------------------------------------------------
    # Teaching scope
    # -------------------------------------------------------------------------

    def get_teaching_assignments(self, faculty_id: str) -> List[Dict[str, Any]]:
        """Every (course, section) the faculty member teaches, for the session launcher."""
        return [
            {
                'course_id': r['course_id'],
                'course_code': r['course_code'],
                'course_name': r['course_name'],
                'section': r['section'],
                'student_count': r['student_count'],
            }
            for r in CourseSectionModel.for_faculty(faculty_id, self.db_path)
        ]

    def get_all_faculty(self) -> List[Dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute("SELECT faculty_id, name, email, department FROM faculty ORDER BY name;").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_sections(self) -> List[str]:
        """Sections that exist in the student directory (drives every section dropdown)."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT DISTINCT UPPER(section) AS section FROM students WHERE section IS NOT NULL AND section != '' ORDER BY 1;"
        ).fetchall()
        conn.close()
        return [r['section'] for r in rows]

    # -------------------------------------------------------------------------
    # Student Operations
    # -------------------------------------------------------------------------

    def get_all_students(self, faculty_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Students with face-enrolment status; scoped to a teacher's sections when faculty_id is given."""
        conn = self._conn()
        if faculty_id:
            rows = conn.execute(
                """
                SELECT DISTINCT s.* FROM students s
                JOIN enrollments e ON e.student_id = s.student_id
                JOIN course_sections cs ON cs.course_id = e.course_id AND cs.section = UPPER(s.section)
                WHERE cs.faculty_id = ?
                ORDER BY s.roll_number;
                """,
                (faculty_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM students ORDER BY section, roll_number;").fetchall()

        course_map: Dict[str, List[str]] = {}
        for er in conn.execute(
            "SELECT e.student_id, c.course_code FROM enrollments e JOIN courses c ON e.course_id = c.course_id ORDER BY c.course_code;"
        ).fetchall():
            course_map.setdefault(er['student_id'], []).append(er['course_code'])
        conn.close()

        results = []
        for row in rows:
            samples = face_service.get_sample_count(row['student_id'])
            results.append({
                'id': row['student_id'],
                'student_id': row['student_id'],
                'roll_no': row['roll_number'],
                'name': row['name'],
                'email': row['email'],
                'section': (row['section'] or 'A').upper(),
                'has_face': samples > 0,
                'face_samples_count': samples,
                'course_codes': course_map.get(row['student_id'], []),
            })
        return results

    def create_student(self, roll_no: str, name: str, email: str, program: str = "B.Tech CSE",
                       semester: int = 5, section: str = "A") -> Dict[str, Any]:
        """
        Register a student. They are enrolled automatically in every course that is taught to
        their section, so a new student appears on the right rosters straight away.
        """
        roll_no, name, email = roll_no.strip(), name.strip(), email.strip()
        section = (section or "A").strip().upper()

        conn = self._conn()
        existing = conn.execute(
            "SELECT student_id FROM students WHERE roll_number = ? OR email = ?;", (roll_no, email)
        ).fetchone()
        if existing:
            conn.close()
            return self.get_student_by_id(existing['student_id'])

        max_num = 0
        for r in conn.execute("SELECT student_id FROM students WHERE student_id LIKE 'STU%';").fetchall():
            tail = r['student_id'][3:]
            if tail.isdigit():
                max_num = max(max_num, int(tail))
        new_sid = f"STU{max_num + 1:03d}"

        conn.execute(
            """
            INSERT INTO students (student_id, roll_number, name, email, program, semester, face_registered, section)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?);
            """,
            (new_sid, roll_no, name, email, program, semester, section)
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO enrollments (course_id, student_id)
            SELECT course_id, ? FROM course_sections WHERE section = ?;
            """,
            (new_sid, section)
        )
        conn.commit()
        conn.close()
        return self.get_student_by_id(new_sid)

    def get_student_by_id(self, student_id: Any) -> Optional[Dict[str, Any]]:
        """Look up a student by canonical student_id (or roll number)."""
        key = str(student_id).strip().lower()
        return next(
            (s for s in self.get_all_students() if s['student_id'].lower() == key or s['roll_no'].lower() == key),
            None
        )

    def get_student_by_roll(self, roll_no: str) -> Optional[Dict[str, Any]]:
        return self.get_student_by_id(roll_no)

    def set_student_face_registered(self, student_id: str, face_registered: bool = True):
        conn = self._conn()
        conn.execute(
            "UPDATE students SET face_registered = ? WHERE student_id = ? OR roll_number = ?;",
            (1 if face_registered else 0, str(student_id), str(student_id))
        )
        conn.commit()
        conn.close()

    # -------------------------------------------------------------------------
    # Course Operations
    # -------------------------------------------------------------------------

    def get_all_courses(self, faculty_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Course catalogue with per-section teachers; scoped to a teacher's own courses when given."""
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT c.*, f.name AS faculty_name,
                   (SELECT COUNT(*) FROM enrollments e WHERE e.course_id = c.course_id) AS enrolled_count,
                   (SELECT COUNT(*) FROM class_sessions s WHERE s.course_id = c.course_id) AS sessions_count
            FROM courses c LEFT JOIN faculty f ON c.faculty_id = f.faculty_id
            ORDER BY c.course_code ASC;
            """
        ).fetchall()
        conn.close()

        results = []
        for r in rows:
            sections = CourseSectionModel.for_course(r['course_id'], self.db_path)
            if faculty_id:
                mine = [s for s in sections if s['faculty_id'] == faculty_id]
                if not mine and r['faculty_id'] != faculty_id:
                    continue
                if not sections:  # legacy course without section assignments
                    mine = []
            else:
                mine = sections
            results.append({
                'id': r['course_id'],
                'course_id': r['course_id'],
                'code': r['course_code'],
                'name': r['course_name'],
                'faculty_id': r['faculty_id'],
                'faculty_name': r['faculty_name'] or '',
                'credits': r['credits'],
                'semester': r['semester'],
                'academic_year': r['academic_year'],
                'enrolled_count': r['enrolled_count'],
                'sessions_count': r['sessions_count'],
                'sections': sections,
                'my_sections': mine,
                'description': f"{r['credits']} credits | Semester {r['semester']} | {r['academic_year']}",
            })
        return results

    def create_course(
        self,
        code: str,
        name: str,
        description: str = "",
        faculty_id: Optional[str] = None,
        credits: Optional[int] = None,
        semester: Optional[int] = None,
        academic_year: Optional[str] = None,
        sections: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Create a course led by ``faculty_id``. For every section in ``sections`` the lead
        faculty is assigned as teacher and that section's students are enrolled; the admin can
        then reassign individual sections to other teachers.
        """
        code = code.strip().upper()
        name = name.strip()
        if not faculty_id:
            raise ValueError("Faculty assignment is required to create a course.")

        conn = self._conn()
        fac_row = conn.execute("SELECT faculty_id FROM faculty WHERE faculty_id = ?;", (faculty_id,)).fetchone()
        if not fac_row:
            conn.close()
            raise ValueError(f"Faculty '{faculty_id}' does not exist.")

        course_credits = int(credits) if credits is not None else getattr(Config, 'DEFAULT_COURSE_CREDITS', 3)
        if course_credits <= 0:
            conn.close()
            raise ValueError(f"Invalid course credits: {course_credits}. Must be a positive integer.")

        course_semester = int(semester) if semester is not None else getattr(Config, 'DEFAULT_COURSE_SEMESTER', 5)
        if not (1 <= course_semester <= 12):
            conn.close()
            raise ValueError(f"Invalid semester: {course_semester}. Must be between 1 and 12.")

        course_year = str(academic_year).strip() if academic_year else getattr(Config, 'DEFAULT_ACADEMIC_YEAR', '2026-2027')
        course_id = f"CRS-{code}"
        try:
            conn.execute(
                """
                INSERT INTO courses (course_id, course_code, course_name, credits, faculty_id, semester, academic_year)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (course_id, code, name, course_credits, faculty_id, course_semester, course_year)
            )
            conn.commit()
        except Exception:
            conn.close()
            return None
        conn.close()

        for sec in (sections or []):
            self.assign_section(course_id, sec, faculty_id, enroll_students=True)
        return next((c for c in self.get_all_courses() if c['course_id'] == course_id), None)

    def assign_section(self, course_id: str, section: str, faculty_id: str, enroll_students: bool = True) -> None:
        """Make ``faculty_id`` the teacher of one section of a course (optionally enrolling the section)."""
        section = section.strip().upper()
        CourseSectionModel.assign(course_id, section, faculty_id, self.db_path)
        if enroll_students:
            EnrollmentModel.enroll_section(course_id, section, self.db_path)

    def remove_section(self, course_id: str, section: str, unenroll_students: bool = False) -> None:
        CourseSectionModel.unassign(course_id, section, self.db_path)
        if unenroll_students:
            EnrollmentModel.unenroll_section(course_id, section, self.db_path)

    # -------------------------------------------------------------------------
    # Sessions
    # -------------------------------------------------------------------------

    def start_session(self, course_id: Any, topic: str = "Regular Lecture",
                      faculty_id: Optional[str] = None, section: str = "All") -> str:
        """Start an attendance session for one section of a course."""
        conn = self._conn()
        course = conn.execute(
            "SELECT course_id FROM courses WHERE course_id = ? OR course_code = ?;", (str(course_id), str(course_id))
        ).fetchone()
        conn.close()
        if not course:
            raise ValueError(f"Course '{course_id}' does not exist.")
        if not faculty_id:
            raise ValueError("Faculty assignment is required to start an attendance session.")

        from attendance_service import AttendanceService
        success, msg, session = AttendanceService.start_session(
            course_id=course['course_id'],
            faculty_id=faculty_id,
            topic=topic or "Regular Lecture",
            section=section or "All",
            db_path=self.db_path
        )
        if success and session:
            return session['session_id']
        raise RuntimeError(msg)

    def _session_rows(self, faculty_id: Optional[str], limit: Optional[int] = None, course_id: Optional[str] = None):
        sql = """
            SELECT s.session_id, s.course_id, s.date, s.start_time, s.end_time, s.status,
                   COALESCE(UPPER(s.section), 'ALL') AS section, s.topic,
                   c.course_code, c.course_name,
                   (SELECT COUNT(*) FROM attendance_records a WHERE a.session_id = s.session_id AND a.status IN ('Present','Late')) AS present_count,
                   (SELECT COUNT(*) FROM enrollments e JOIN students st ON st.student_id = e.student_id
                     WHERE e.course_id = s.course_id
                       AND (COALESCE(UPPER(s.section), 'ALL') = 'ALL' OR UPPER(st.section) = UPPER(s.section))) AS total_enrolled
            FROM class_sessions s LEFT JOIN courses c ON s.course_id = c.course_id
            WHERE 1 = 1
            """
        params: list = []
        if faculty_id:
            sql += " AND s.faculty_id = ?"
            params.append(faculty_id)
        if course_id:
            sql += " AND s.course_id = ?"
            params.append(course_id)
        sql += " ORDER BY s.date DESC, s.start_time DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        conn = self._conn()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows

    @staticmethod
    def _session_payload(r) -> Dict[str, Any]:
        enrolled, present = r['total_enrolled'] or 0, r['present_count'] or 0
        return {
            'id': r['session_id'],
            'course_id': r['course_id'],
            'course_code': r['course_code'] or r['course_id'],
            'course_name': r['course_name'] or 'Session',
            'date': r['date'],
            'start_time': r['start_time'],
            'end_time': r['end_time'],
            'section': r['section'].title() if r['section'] == 'ALL' else r['section'],
            'topic': r['topic'],
            'status': r['status'].upper(),
            'present_count': present,
            'total_enrolled': enrolled,
            'attendance_percentage': _pct(present, enrolled),
        }

    def get_dashboard_data(self, faculty_id: Optional[str] = None) -> Dict[str, Any]:
        """Dashboard metrics, scoped to one teacher (faculty_id) or institution-wide (None)."""
        sessions = [self._session_payload(r) for r in self._session_rows(faculty_id)]
        courses = self.get_all_courses(faculty_id)
        students = self.get_all_students(faculty_id)

        total_present = sum(s['present_count'] for s in sessions)
        total_expected = sum(s['total_enrolled'] for s in sessions)
        avg = f"{round(total_present / total_expected * 100, 1)}%" if total_expected else "N/A"

        return {
            'stats': {
                'active_sessions': sum(1 for s in sessions if s['status'] == 'ACTIVE'),
                'total_students': len(students),
                'faces_enrolled': sum(1 for s in students if s['has_face']),
                'total_courses': len(courses),
                'avg_attendance': avg,
            },
            'recent_sessions': sessions[:10],
            'courses': courses,
        }

    def get_session_details(self, session_id: Any) -> Optional[Dict[str, Any]]:
        from models import ClassSessionModel
        session = ClassSessionModel.get_by_id(str(session_id), self.db_path)
        if not session:
            return None
        enrolled = self.get_enrolled_students_for_session(session_id)
        present = len(self.get_attendance_records(session_id))
        return {
            'id': session['session_id'],
            'course_id': session['course_id'],
            'faculty_id': session.get('faculty_id'),
            'course_code': session.get('course_code') or session['course_id'],
            'course_name': session.get('course_name') or 'Attendance Session',
            'faculty_name': session.get('faculty_name') or '',
            'date': session.get('date'),
            'start_time': session.get('start_time'),
            'status': session['status'].upper(),
            'section': session.get('section') or 'All',
            'total_enrolled': len(enrolled),
            'present_count': present,
            'attendance_percentage': _pct(present, len(enrolled)),
        }

    def get_enrolled_students_for_session(self, session_id: Any) -> List[Dict[str, Any]]:
        """The session roster: students enrolled in the course AND belonging to the session's section."""
        from models import ClassSessionModel
        session = ClassSessionModel.get_by_id(str(session_id), self.db_path)
        if not session:
            return []
        rows = EnrollmentModel.get_enrolled_students(session['course_id'], self.db_path, section=session.get('section'))
        return [
            {
                'id': r['student_id'],
                'student_id': r['student_id'],
                'roll_no': r['roll_number'],
                'name': r['name'],
                'email': r['email'],
                'section': (r['section'] or 'A').upper(),
            }
            for r in rows
        ]

    def get_attendance_records(self, session_id: Any) -> List[Dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT a.*, s.name AS student_name, s.roll_number AS roll_no
            FROM attendance_records a JOIN students s ON a.student_id = s.student_id
            WHERE a.session_id = ? ORDER BY a.timestamp ASC;
            """,
            (str(session_id),)
        ).fetchall()
        conn.close()
        return [
            {
                'student_id': r['student_id'],
                'roll_no': r['roll_no'],
                'student_name': r['student_name'],
                'timestamp': r['timestamp'],
                'method': r['marking_method'],
                'status': r['status'],
                'confidence': r['confidence_score'],
            }
            for r in rows
        ]

    def get_session_report(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Present / absent breakdown for one session (absent = on the roster, no record)."""
        details = self.get_session_details(session_id)
        if not details:
            return None
        records = {r['student_id']: r for r in self.get_attendance_records(session_id)}
        roster = self.get_enrolled_students_for_session(session_id)
        return {
            'session': details,
            'present': [{**s, **records[s['student_id']]} for s in roster if s['student_id'] in records],
            'absent': [s for s in roster if s['student_id'] not in records],
        }

    def record_attendance(self, session_id: Any, student_id: Any, method: str = 'Face Recognition',
                          confidence: Optional[float] = None) -> bool:
        student = self.get_student_by_id(student_id)
        if not student:
            return False
        from attendance_service import AttendanceService
        ok, _, _ = AttendanceService.record_attendance(
            session_id=str(session_id),
            student_id=student['student_id'],
            method=method,
            confidence_score=confidence,
            db_path=self.db_path
        )
        return ok

    # -------------------------------------------------------------------------
    # Reports
    # -------------------------------------------------------------------------

    def get_reports_data(self, course_id: Optional[str] = None, section: Optional[str] = None,
                         faculty_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Attendance analytics. ``course_id`` / ``section`` narrow the view; ``faculty_id`` restricts a
        teacher to their own course sections.
        """
        from attendance_service import AttendanceService

        courses = self.get_all_courses(faculty_id)
        if isinstance(section, str) and section.upper() in ('', 'ALL'):
            section = None
        section = section.upper() if section else None

        selected = None
        if course_id and str(course_id).lower() != 'all':
            selected = next(
                (c for c in courses if str(c['course_id']) == str(course_id) or str(c['code']).lower() == str(course_id).lower()),
                None
            )
        targets = [selected] if selected else courses

        student_reports, session_logs = [], []
        for c in targets:
            allowed = {s['section'] for s in c['my_sections']} if faculty_id and c['my_sections'] else None
            rep = AttendanceService.get_course_attendance_report(c['course_id'], self.db_path, section=section)
            for sr in rep.get('student_reports', []):
                if allowed is not None and sr['section'] not in allowed:
                    continue
                student_reports.append({
                    'student_id': sr['student_id'],
                    'roll_no': sr['roll_number'],
                    'student_name': sr['name'],
                    'section': sr['section'],
                    'course_id': c['course_id'],
                    'course_code': c['code'],
                    'attended_sessions': sr['attended_sessions'],
                    'total_sessions': sr['total_sessions'],
                    'percentage': sr['attendance_percentage'],
                })
            for r in self._session_rows(None, course_id=c['course_id']):
                sec = r['section']
                if section and sec not in (section, 'ALL'):
                    continue
                if allowed is not None and sec != 'ALL' and sec not in allowed:
                    continue
                session_logs.append(self._session_payload(r))

        measured = [s for s in student_reports if s['percentage'] is not None]
        return {
            'courses': courses,
            'sections': self.get_sections(),
            'student_reports': student_reports,
            'session_logs': session_logs,
            'summary': {
                'total_sessions': len(session_logs),
                'total_students': len(student_reports),
                'eligible_count': sum(1 for s in measured if s['percentage'] >= LOW_ATTENDANCE_THRESHOLD),
                'warning_count': sum(1 for s in measured if s['percentage'] < LOW_ATTENDANCE_THRESHOLD),
            },
        }


# Global singleton instance
data_provider = DataProvider()
