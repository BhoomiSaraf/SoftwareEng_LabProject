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

---

## 4. Live Session Attendance HTTP API (Consolidated Backend Specification)

The live session attendance endpoints in `run_frontend_dev.py` delegate all eligibility checks, session lifecycle validations, and duplicate prevention directly to `AttendanceService` and the persistent SQLite database.

### 4.1 Live Face Recognition Attendance
- **Route:** `POST /api/sessions/<session_id>/recognize`
- **Request Body:**
  ```json
  {
    "image": "data:image/jpeg;base64,..."
  }
  ```
- **Responses:**
  - **Marked Present (`200 OK`):**
    ```json
    {
      "status": "marked",
      "student": {
        "id": 1,
        "student_id": "STU001",
        "roll_no": "229301045",
        "name": "Bhoomi Saraf",
        "email": "bhoomi.229301045@muj.manipal.edu"
      },
      "confidence": 0.942,
      "timestamp": "09:05:12 AM",
      "method": "FACE_RECOGNITION"
    }
    ```
  - **Duplicate Attempt Blocked (`200 OK`):**
    ```json
    {
      "status": "already_marked",
      "student": { ... },
      "confidence": 0.942,
      "message": "Duplicate attendance blocked: Bhoomi Saraf (229301045) is already marked 'Present' for session SES-..."
    }
    ```
  - **Not Enrolled in Course (`200 OK`):**
    ```json
    {
      "status": "not_enrolled",
      "student": { ... },
      "confidence": 0.92,
      "message": "Enrollment Error: Kabir Verma (229301275) is not enrolled in course CSE3101."
    }
    ```
  - **Unrecognized Face (`200 OK`):**
    ```json
    {
      "status": "unrecognized",
      "confidence": 0.45,
      "message": "Face detected (highest confidence 45.0% is below recognition threshold 65%)."
    }
    ```
  - **No Face in View (`200 OK`):**
    ```json
    {
      "status": "no_face",
      "message": "No face detected in camera view. Position face in center frame."
    }
    ```
  - **Multiple Faces in View (`200 OK`):**
    ```json
    {
      "status": "multiple_faces",
      "message": "Multiple faces detected. Please present one face at a time for attendance."
    }
    ```
  - **Session Inactive / Closed (`400 Bad Request`):**
    ```json
    {
      "status": "session_inactive",
      "message": "Attendance rejected: Session SES-... is 'Completed'. Attendance can only be recorded during an Active session."
    }
    ```
  - **Session Not Found (`404 Not Found`):**
    ```json
    {
      "status": "error",
      "error": "Session not found",
      "message": "Session 'SES-...' not found."
    }
    ```
  - **Missing Image Data (`400 Bad Request`):**
    ```json
    {
      "status": "error",
      "error": "Missing frame image data",
      "message": "Missing frame image data"
    }
    ```

### 4.2 Manual Attendance Override
- **Route:** `POST /api/sessions/<session_id>/mark-manual`
- **Request Body:**
  ```json
  {
    "student_id": 6
  }
  ```
  *(Accepts numeric IDs e.g. `6`, string keys e.g. `"STU006"`, or roll numbers e.g. `"21BCE006"`)*
- **Responses:**
  - **Marked Present (`200 OK`):**
    ```json
    {
      "status": "marked",
      "student": { ... },
      "timestamp": "09:06:00 AM",
      "method": "MANUAL"
    }
    ```
  - **Already Marked (`200 OK`):**
    ```json
    {
      "status": "already_marked",
      "student": { ... },
      "message": "Duplicate attendance blocked: ..."
    }
    ```
  - **Not Enrolled (`200 OK`):**
    ```json
    {
      "status": "not_enrolled",
      "student": { ... },
      "message": "Enrollment Error: ..."
    }
    ```
  - **Session Inactive (`400 Bad Request`):**
    ```json
    {
      "status": "session_inactive",
      "message": "Attendance rejected: Session is 'Completed'."
    }
    ```
  - **Student or Session Not Found (`404 Not Found`):**
    ```json
    {
      "error": "Student not found"
    }
    ```

### 4.3 End Session Lifecycle
- **Route:** `POST /api/sessions/<session_id>/end`
- **Behavior:** Persistently transitions session state in `class_sessions` from `'Active'` to `'Completed'`, recording the exact closure timestamp in `end_time`.
- **Responses:**
  - **Success (`200 OK`):**
    ```json
    {
      "status": "success",
      "message": "Attendance session #SES-... ended and archived.",
      "session": {
        "session_id": "SES-...",
        "course_id": "CRS-CSE3132",
        "status": "Completed",
        "end_time": "10:30:00",
        ...
      }
    }
    ```
  - **Already Completed or Inactive (`400 Bad Request`):**
    ```json
    {
      "status": "error",
      "error": "Session close failed",
      "message": "Session 'SES-...' is already Completed."
    }
    ```
  - **Session Not Found (`404 Not Found`):**
    ```json
    {
      "status": "error",
      "error": "Session not found",
      "message": "Session '...' not found."
    }
    ```

---

## 5. Authentication, Authorization & Security Policies

### 5.1 Identity & Session Authentication
- **Mechanism:** Flask session cookies signed with `SECRET_KEY` loaded via environment variable (`config.py`).
- **Cookie Security:** `HttpOnly=True`, `SameSite=Lax`, `Secure=True` in production.
- **Roles:**
  - `admin`: Global access across all courses, sessions, and management functions.
  - `faculty`: Instructors authorized to manage attendance and enrollments for assigned courses.
  - `student`: Read-only student identity (prohibited from invoking faculty attendance operations or admin views).

### 5.2 API Authentication & Access Boundaries
| Endpoint | Method | Required Role / Token | Access Rule |
| :--- | :--- | :--- | :--- |
| `/api/sessions/<id>/recognize` | `POST` | `faculty`, `admin`, or `X-API-Key` | Must be assigned instructor, admin, or verified camera kiosk |
| `/api/sessions/<id>/mark-manual`| `POST` | `faculty`, `admin` | Must be assigned instructor or admin |
| `/api/sessions/<id>/end` | `POST` | `faculty`, `admin` | Must be assigned instructor or admin |
| `/api/courses/<id>/enroll` | `POST` | `faculty`, `admin` | Must be assigned course instructor or admin |
| `/api/courses/<id>/enrollment-data`| `GET` | Authenticated user | Returns roster and enrolled IDs |
| `/api/students/<id>/register-face`| `POST` | `faculty`, `admin` | Registers face biometric embeddings |
| `/api/reports/export-csv` | `GET` | `faculty`, `admin` | Generates RFC 4180 attendance CSV export |

### 5.3 Error Status Responses
- **`401 Unauthorized`:**
  Returned when unauthenticated requests access protected API endpoints.
  ```json
  {
    "status": "error",
    "error": "Unauthorized",
    "message": "Authentication required to access this resource."
  }
  ```
- **`403 Forbidden`:**
  Returned when an authenticated user lacks the required role or attempts cross-instructor session modification.
  ```json
  {
    "status": "error",
    "error": "Forbidden",
    "message": "Access denied: insufficient permissions."
  }
  ```


