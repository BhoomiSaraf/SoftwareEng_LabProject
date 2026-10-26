# Backend & Database Shared Interface Contract
**Project:** Smart Attendance System using Face-Recognition Scanner (CSE3132)  
**Assigned Module:** Backend & Database  
**Branch:** `feature/backend-database`  
**Database:** SQLite (`smart_attendance.db`)

---

## 1. Interface for Developer 2 (Face Recognition Module)

The face recognition module is responsible for capturing camera frames, detecting faces, matching against embeddings, and returning a student ID or an unknown result.

### 1.1 Direct Function Interface
```python
from attendance_service import AttendanceService

# Call this function once a face match is identified:
success, message, record = AttendanceService.record_attendance(
    session_id="SES-CSE3132-20261027103000", # Active session ID
    student_id="STU001",                      # or roll_number e.g. "229301045"
    method="Face Recognition",               # or "Simulated Scanner"
    confidence_score=0.96                    # Optional match confidence (0.0 to 1.0)
)
```

### 1.2 Return Values & Status Handling
| `success` | Scenario | Example `message` | `record` object |
| :--- | :--- | :--- | :--- |
| `True` | Verified & Recorded | `"Attendance marked: Bhoomi Saraf (229301045) is Present."` | Dict containing `attendance_id`, `timestamp`, `status`, etc. |
| `False` | Duplicate Attempt | `"Duplicate attendance blocked: Bhoomi Saraf is already marked Present..."` | Existing attendance record dict |
| `False` | Session Inactive/Ended | `"Attendance rejected: Session SES-... is 'Completed'..."` | `None` |
| `False` | Student Not Enrolled | `"Enrollment Error: Student ... is not enrolled in course ..."` | `None` |
| `False` | Unknown Student | `"Student 'XYZ' is not registered in the system."` | `None` |

---

## 2. Interface for Developer 3 (Frontend & Reports Module)

### 2.1 Session Management
```python
from attendance_service import AttendanceService
from models import ClassSessionModel

# 1. Start a session (called when faculty clicks 'Start Session'):
success, msg, session = AttendanceService.start_session(
    course_id="CRS-CSE3132",
    faculty_id="FAC001",
    topic="Lab 4: Face Recognition Evaluation",
    room="Lab 204, Academic Block 3"
)

# 2. Close a session (called when faculty clicks 'End Session'):
success, msg, session = AttendanceService.close_session(session_id="SES-CSE3132-...")

# 3. Check active session for a course:
active_session = ClassSessionModel.get_active_session_for_course(course_id="CRS-CSE3132")
```

### 2.2 Attendance Viewing & Manual Correction
```python
from models import AttendanceRecordModel

# 1. Fetch live attendance for a specific session:
records = AttendanceRecordModel.get_session_attendance(session_id="SES-...")
# Returns list of dicts:
# [{'attendance_id': 1, 'student_id': 'STU001', 'roll_number': '229301045', 
#   'student_name': 'Bhoomi Saraf', 'timestamp': '2026-10-27 10:32:00', 
#   'status': 'Present', 'marking_method': 'Face Recognition', 'confidence_score': 0.96}]

# 2. Faculty manual correction (e.g. toggle Present / Late / Absent):
success, msg = AttendanceService.manual_override(
    attendance_id=1,
    new_status="Late", # 'Present' | 'Late' | 'Absent'
    faculty_name="Dr. Rajesh Kumar"
)
```

### 2.3 Reports & CSV Export
```python
from attendance_service import AttendanceService

# 1. Calculate course attendance statistics:
report = AttendanceService.get_course_attendance_report(course_id="CRS-CSE3132")
# Returns:
# {
#   'course': {...},
#   'total_sessions_held': 4,
#   'student_reports': [
#       {
#           'student_id': 'STU001',
#           'roll_number': '229301045',
#           'name': 'Bhoomi Saraf',
#           'total_sessions': 4,
#           'attended_sessions': 4,
#           'attendance_percentage': 100.0,
#           'low_attendance_warning': False
#       },
#       ...
#   ]
# }

# 2. Generate CSV for file download:
csv_content = AttendanceService.generate_csv_report(course_id="CRS-CSE3132")
```

---

## 3. Database Schema Reference

| Table | Primary Key | Key Foreign Keys & Constraints |
| :--- | :--- | :--- |
| `users` | `id` | `username` (UNIQUE), `role` (`'admin'`, `'faculty'`, `'student'`) |
| `faculty` | `faculty_id` | `user_id` -> `users.id`, `email` (UNIQUE) |
| `students` | `student_id` | `roll_number` (UNIQUE), `face_registered` (0 or 1) |
| `courses` | `course_id` | `faculty_id` -> `faculty.faculty_id`, `course_code` (UNIQUE) |
| `enrollments` | `enrollment_id` | `course_id`, `student_id`, `UNIQUE(course_id, student_id)` |
| `class_sessions` | `session_id` | `course_id`, `faculty_id`, `status` (`'Active'`, `'Completed'`) |
| `attendance_records` | `attendance_id` | `session_id`, `student_id`, `course_id`, **`UNIQUE(session_id, student_id)`** |
