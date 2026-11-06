"""
Smart Attendance System - Frontend Development Server & Backend API Engine
Connects the presentation tier directly to the authoritative SQLite database,
biometric face recognition service, and attendance business logic.
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import io
import csv
import datetime
import logging
from flask import Flask, jsonify, request, Response, session as flask_session
from flask_wtf.csrf import CSRFProtect, CSRFError, validate_csrf
from config import Config
from auth import AuthService, login_required, role_required, faculty_required, admin_required, is_api_request
from frontend_bp import frontend_bp
from face_recognition_service import face_service
from data_provider import data_provider
from attendance_service import AttendanceService
from models import ClassSessionModel, StudentModel, EnrollmentModel, AttendanceRecordModel, CourseModel

logger = logging.getLogger("SmartAttendanceApp")

app = Flask(__name__)
app.config.from_object(Config)

# Enable synchronised CSRF token protection
csrf = CSRFProtect(app)

# Attach AuthService and persistent SQLite Data Provider to Flask app
app.auth_service = AuthService
app.data_provider = data_provider

# Register Frontend Blueprint
app.register_blueprint(frontend_bp)

# Embeddings persistence directory and path configuration
EMBEDDINGS_DIR = getattr(Config, 'EMBEDDINGS_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
EMBEDDINGS_FILE = getattr(Config, 'EMBEDDINGS_FILE', os.path.join(EMBEDDINGS_DIR, 'embeddings.npz'))


def get_embeddings_path():
    """Retrieve the authoritative configured embeddings path from app config, data provider, or Config."""
    return (
        app.config.get('EMBEDDINGS_FILE')
        or getattr(getattr(app, 'data_provider', None), 'embeddings_path', None)
        or getattr(data_provider, 'embeddings_path', None)
        or EMBEDDINGS_FILE
    )


# Load previously saved biometric embeddings into face_service
_init_emb = get_embeddings_path()
if _init_emb and os.path.exists(_init_emb):
    face_service.load_embeddings(_init_emb)


def get_db_path():
    return app.config.get('DB_PATH') or getattr(getattr(app, 'data_provider', None), 'db_path', None)


def find_canonical_student(identifier, db_path=None):
    """Resolve any input identifier (canonical student_id, roll_number, or numeric index) to the DB record."""
    if identifier is None:
        return None
    raw_id = str(identifier).strip()
    if not raw_id:
        return None

    # 1. Direct student_id match (e.g. STU001)
    student = StudentModel.get_by_id(raw_id, db_path=db_path)
    if student:
        return student

    # 2. Roll number match (e.g. 21BCE001 or 229301045)
    student = StudentModel.get_by_roll(raw_id, db_path=db_path)
    if student:
        return student

    # 3. Numeric ID match (e.g. 1 -> STU001)
    if raw_id.isdigit():
        formatted_sid = f"STU{int(raw_id):03d}"
        student = StudentModel.get_by_id(formatted_sid, db_path=db_path)
        if student:
            return student

    # 4. Fallback search via data_provider
    dp = getattr(app, 'data_provider', data_provider)
    if dp:
        dp_student = dp.get_student_by_id(int(raw_id)) if raw_id.isdigit() else dp.get_student_by_roll(raw_id)
        if dp_student and dp_student.get('student_id'):
            student = StudentModel.get_by_id(dp_student['student_id'], db_path=db_path)
            if student:
                return student

    return None


def format_student_payload(student):
    sid = student['student_id']
    numeric_id = int(sid[3:]) if sid.startswith('STU') and sid[3:].isdigit() else sid
    roll = student.get('roll_number') or student.get('roll_no', '')
    return {
        'id': numeric_id,
        'student_id': sid,
        'roll_no': roll,
        'roll_number': roll,
        'name': student['name'],
        'email': student['email']
    }


def resolve_course_record(course_identifier, db_path=None):
    """Resolve numeric course ID, course_code, or course_id to DB row."""
    if course_identifier is None:
        return None
    c_str = str(course_identifier).strip()
    course = CourseModel.get_by_id(c_str, db_path=db_path)
    if course:
        return course

    dp = getattr(app, 'data_provider', data_provider)
    courses = dp.get_all_courses() if (dp and hasattr(dp, 'get_all_courses')) else CourseModel.get_all(db_path=db_path)
    for c in courses:
        if str(c['id']) == c_str or str(c['course_id']) == c_str or str(c['code']).lower() == c_str.lower():
            return CourseModel.get_by_id(c['course_id'], db_path=db_path)
    return None


# Biometric Face Registration Endpoint
@app.route('/api/students/<student_id>/register-face', methods=['POST'])
@role_required('faculty', 'admin')
def api_register_face(student_id):
    data = request.get_json(silent=True) or {}
    image_data = data.get('image')
    if not image_data:
        return jsonify({'error': 'No image data payload received'}), 400

    db_path = get_db_path()
    student = find_canonical_student(student_id, db_path=db_path)
    if not student:
        return jsonify({'error': 'Student not found'}), 404

    # Real biometric face enrollment via Haar Cascade + MobileNetV3
    res = face_service.register_student_face(student['student_id'], image_data)
    if not res.get('success'):
        return jsonify({
            'status': 'error',
            'error': res.get('message', 'Face registration failed.'),
            'message': res.get('message', 'Face registration failed.')
        }), 400

    # Also register aliases
    face_service.register_student_face(student['roll_number'], image_data)
    num_id = student['student_id'][3:] if student['student_id'].startswith('STU') and student['student_id'][3:].isdigit() else str(student_id)
    face_service.register_student_face(str(int(num_id)), image_data)

    # Persist numeric embeddings to configured storage path
    emb_path = get_embeddings_path()
    save_ok = face_service.save_embeddings(emb_path)
    if not save_ok or not os.path.exists(emb_path):
        return jsonify({
            'status': 'error',
            'error': 'Storage persistence failure',
            'message': 'Failed to persist face embedding to configured storage.'
        }), 500

    # Update SQLite database only after storage persistence is confirmed
    StudentModel.set_face_registered(student['student_id'], True, db_path=db_path)
    dp = getattr(app, 'data_provider', data_provider)
    if dp:
        dp.set_student_face_registered(student['student_id'], True)

    samples_count = len(face_service._registered_embeddings.get(student['student_id'], []))

    return jsonify({
        'status': 'success',
        'message': f"Face biometric embeddings computed and registered for {student['name']} ({student['roll_number']}).",
        'embedding_dim': res.get('embedding_dim', 576),
        'samples_count': samples_count
    })


@app.route('/api/courses/<course_id>/enrollment-data', methods=['GET'])
@login_required
def api_course_enrollment_data(course_id):
    db_path = get_db_path()
    course = resolve_course_record(course_id, db_path=db_path)
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    all_students = data_provider.get_all_students()
    enrolled_students = EnrollmentModel.get_enrolled_students(course['course_id'], db_path=db_path)
    enrolled_sid_set = {s['student_id'] for s in enrolled_students}

    enrolled_ids = [s['id'] for s in all_students if s['student_id'] in enrolled_sid_set]

    return jsonify({
        'course_id': course['course_id'],
        'course_code': course['course_code'],
        'students': all_students,
        'enrolled_ids': enrolled_ids
    })


@app.route('/api/courses/<course_id>/enroll', methods=['POST'])
@role_required('faculty', 'admin')
def api_enroll_course(course_id):
    data = request.get_json(silent=True) or {}
    raw_student_ids = data.get('student_ids', [])

    db_path = get_db_path()
    course = resolve_course_record(course_id, db_path=db_path)
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    # Verify course instructor ownership
    user = flask_session.get('user', {})
    if user.get('role') != 'admin' and user.get('faculty_id') and course.get('faculty_id'):
        if course['faculty_id'] != user.get('faculty_id'):
            return jsonify({
                'status': 'error',
                'error': 'Forbidden',
                'message': 'You are not authorized to modify enrollments for another instructor\'s course.'
            }), 403

    actual_course_id = course['course_id']

    # Update enrollments in SQLite database
    import database
    conn = database.get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        # Delete existing enrollments for this course
        cursor.execute("DELETE FROM enrollments WHERE course_id = ?;", (actual_course_id,))

        enrolled_count = 0
        for raw_sid in raw_student_ids:
            st = find_canonical_student(raw_sid, db_path=db_path)
            if st:
                cursor.execute(
                    "INSERT OR IGNORE INTO enrollments (course_id, student_id) VALUES (?, ?);",
                    (actual_course_id, st['student_id'])
                )
                enrolled_count += 1

        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'status': 'success',
        'message': f"Enrolled {enrolled_count} students in {course['course_code']}."
    })


# Real Live Face Recognition Endpoint for Attendance Sessions
# Machine-to-machine hardware camera kiosks with a valid CAMERA_API_KEY are exempted from CSRF.
# Browser-session-authenticated requests MUST supply a valid CSRF token.
@app.route('/api/sessions/<session_id>/recognize', methods=['POST'])
@csrf.exempt
def api_recognize(session_id):
    # Authentication & Authorization Check
    # Allowed if:
    # 1. External camera kiosk with valid CAMERA_API_KEY (exempt from CSRF)
    # 2. Browser session with role 'faculty' or 'admin' AND valid CSRF token
    user = flask_session.get('user')
    api_key = request.headers.get('X-API-Key') or request.headers.get('X-API-KEY')
    if not api_key and request.headers.get('Authorization', '').startswith('Bearer '):
        api_key = request.headers.get('Authorization')[7:].strip()

    valid_key = bool(Config.CAMERA_API_KEY and api_key and api_key == Config.CAMERA_API_KEY)

    if valid_key:
        # Machine-to-machine camera kiosk: authenticated via API key, exempt from CSRF
        pass
    elif user:
        # Browser-session authentication: MUST enforce CSRF protection!
        csrf_token = request.headers.get('X-CSRFToken') or request.form.get('csrf_token')
        try:
            validate_csrf(csrf_token)
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error': 'CSRF Error',
                'message': f"CSRF validation failed for session-authenticated camera request: {str(e)}"
            }), 400

        if not AuthService.has_role(user, 'faculty', 'admin'):
            return jsonify({
                'status': 'error',
                'error': 'Forbidden',
                'message': 'Students cannot invoke attendance scanning controls.'
            }), 403
    else:
        return jsonify({
            'status': 'error',
            'error': 'Unauthorized',
            'message': 'Authentication required to access attendance session.'
        }), 401

    data = request.get_json(silent=True) or {}
    image = data.get('image')

    if not image:
        return jsonify({'status': 'error', 'error': 'Missing frame image data', 'message': 'Missing frame image data'}), 400

    db_path = get_db_path()

    # 1. Retrieve session from persistent DB and verify active
    session = ClassSessionModel.get_by_id(str(session_id), db_path=db_path)
    if not session:
        return jsonify({'status': 'error', 'error': 'Session not found', 'message': f"Session '{session_id}' not found."}), 404

    # Verify session instructor ownership if session-authenticated
    if user and user.get('role') != 'admin' and user.get('faculty_id') and session.get('faculty_id'):
        if session['faculty_id'] != user.get('faculty_id'):
            return jsonify({
                'status': 'error',
                'error': 'Forbidden',
                'message': 'You are not authorized to record attendance for another instructor\'s session.'
            }), 403

    if session['status'] != 'Active':
        return jsonify({
            'status': 'session_inactive',
            'message': f"Attendance rejected: Session {session_id} is '{session['status']}'. Attendance can only be recorded during an Active session."
        }), 400

    # Reload embeddings if registry is empty and saved file exists
    emb_path = get_embeddings_path()
    if not face_service.get_registered_student_ids() and emb_path and os.path.exists(emb_path):
        face_service.load_embeddings(emb_path)

    # 2. Perform biometric face matching via Haar Cascade + MobileNetV3
    rec_threshold = getattr(Config, 'RECOGNITION_THRESHOLD', 0.65)
    try:
        match_result = face_service.match_face(image, threshold=rec_threshold)
    except Exception as e:
        logger.exception("Face recognition matching exception")
        return jsonify({'status': 'recognition_error', 'message': 'Face recognition processing failed.'}), 500

    status = match_result.get('status')

    if status == 'NO_FACE_DETECTED':
        return jsonify({
            'status': 'no_face',
            'message': match_result.get('message', 'No face detected in camera view. Position face in center frame.')
        }), 200

    elif status == 'MULTIPLE_FACES_DETECTED':
        return jsonify({
            'status': 'multiple_faces',
            'message': match_result.get('message', 'Multiple faces detected. Please present one face at a time for attendance.')
        }), 200

    elif status == 'UNKNOWN_FACE':
        conf = match_result.get('confidence', 0.0)
        return jsonify({
            'status': 'unrecognized',
            'confidence': conf,
            'message': match_result.get('message', f"Face detected (highest confidence {conf:.1%} is below recognition threshold 65%).")
        }), 200

    elif status == 'ERROR':
        return jsonify({
            'status': 'recognition_error',
            'message': match_result.get('message', 'Failed to process camera frame.')
        }), 400

    elif status != 'MATCHED':
        return jsonify({
            'status': 'unrecognized',
            'message': match_result.get('message', 'Unrecognized face in frame.')
        }), 200

    # 3. Valid match returned: Map to existing canonical student record in DB
    matched_id_str = str(match_result.get('student_id', '')).strip()
    confidence = match_result.get('confidence', 0.9)

    student = find_canonical_student(matched_id_str, db_path=db_path)
    if not student:
        return jsonify({
            'status': 'unrecognized',
            'confidence': confidence,
            'message': f"Face matched identifier '{matched_id_str}', but student record was not found in directory."
        }), 200

    student_payload = format_student_payload(student)

    # 4. Delegate attendance validation and recording to AttendanceService
    try:
        ok, msg, rec = AttendanceService.record_attendance(
            session_id=str(session_id),
            student_id=student['student_id'],
            method='Face Recognition',
            confidence_score=confidence,
            db_path=db_path
        )
    except Exception as e:
        logger.exception("Error in AttendanceService.record_attendance")
        return jsonify({'status': 'error', 'message': 'Database error while recording attendance.'}), 500

    if ok:
        timestamp_str = rec.get('timestamp') or datetime.datetime.now().strftime('%I:%M:%S %p')
        return jsonify({
            'status': 'marked',
            'student': student_payload,
            'confidence': confidence,
            'timestamp': timestamp_str,
            'method': 'FACE_RECOGNITION'
        }), 200
    else:
        msg_lower = msg.lower()
        if "duplicate" in msg_lower or "already marked" in msg_lower:
            return jsonify({
                'status': 'already_marked',
                'student': student_payload,
                'confidence': confidence,
                'message': msg
            }), 200
        elif "not enrolled" in msg_lower or "enrollment error" in msg_lower:
            return jsonify({
                'status': 'not_enrolled',
                'student': student_payload,
                'confidence': confidence,
                'message': msg
            }), 200
        elif "active" in msg_lower or "session" in msg_lower:
            return jsonify({
                'status': 'session_inactive',
                'message': msg
            }), 400
        else:
            return jsonify({
                'status': 'error',
                'message': msg
            }), 500


@app.route('/api/sessions/<session_id>/mark-manual', methods=['POST'])
@role_required('faculty', 'admin')
def api_mark_manual(session_id):
    data = request.get_json(silent=True) or {}
    raw_student_id = data.get('student_id')

    if raw_student_id is None:
        return jsonify({'error': 'Missing student_id payload'}), 400

    db_path = get_db_path()

    # 1. Validate session
    session = ClassSessionModel.get_by_id(str(session_id), db_path=db_path)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    # Authorization: check session instructor ownership
    user = flask_session.get('user', {})
    if user.get('role') != 'admin' and user.get('faculty_id') and session.get('faculty_id'):
        if session['faculty_id'] != user.get('faculty_id'):
            return jsonify({
                'status': 'error',
                'error': 'Forbidden',
                'message': 'You are not authorized to modify attendance for another instructor\'s session.'
            }), 403

    if session['status'] != 'Active':
        return jsonify({
            'status': 'session_inactive',
            'message': f"Attendance rejected: Session {session_id} is '{session['status']}'."
        }), 400

    # 2. Look up student
    student = find_canonical_student(raw_student_id, db_path=db_path)
    if not student:
        return jsonify({'error': 'Student not found'}), 404

    student_payload = format_student_payload(student)

    # 3. Delegate to AttendanceService
    try:
        ok, msg, rec = AttendanceService.record_attendance(
            session_id=str(session_id),
            student_id=student['student_id'],
            method='Manual Override',
            db_path=db_path
        )
    except Exception as e:
        logger.exception("Error in AttendanceService.record_attendance (manual)")
        return jsonify({'status': 'error', 'message': 'Database error while recording attendance.'}), 500

    if ok:
        timestamp_str = rec.get('timestamp') or datetime.datetime.now().strftime('%I:%M:%S %p')
        return jsonify({
            'status': 'marked',
            'student': student_payload,
            'timestamp': timestamp_str,
            'method': 'MANUAL'
        }), 200
    else:
        msg_lower = msg.lower()
        if "duplicate" in msg_lower or "already marked" in msg_lower:
            return jsonify({
                'status': 'already_marked',
                'student': student_payload,
                'message': msg
            }), 200
        elif "not enrolled" in msg_lower or "enrollment error" in msg_lower:
            return jsonify({
                'status': 'not_enrolled',
                'student': student_payload,
                'message': msg
            }), 200
        elif "active" in msg_lower or "session" in msg_lower:
            return jsonify({
                'status': 'session_inactive',
                'message': msg
            }), 400
        else:
            return jsonify({
                'status': 'error',
                'message': msg
            }), 500


@app.route('/api/sessions/<session_id>/end', methods=['POST'])
@role_required('faculty', 'admin')
def api_end_session(session_id):
    db_path = get_db_path()

    session = ClassSessionModel.get_by_id(str(session_id), db_path=db_path)
    if not session:
        return jsonify({
            'status': 'error',
            'error': 'Session not found',
            'message': f"Session '{session_id}' not found."
        }), 404

    # Authorization: check session instructor ownership
    user = flask_session.get('user', {})
    if user.get('role') != 'admin' and user.get('faculty_id') and session.get('faculty_id'):
        if session['faculty_id'] != user.get('faculty_id'):
            return jsonify({
                'status': 'error',
                'error': 'Forbidden',
                'message': 'You are not authorized to close another instructor\'s session.'
            }), 403

    success, msg, closed_session = AttendanceService.close_session(str(session_id), db_path=db_path)

    if not success:
        return jsonify({
            'status': 'error',
            'error': 'Session close failed',
            'message': msg
        }), 400

    return jsonify({
        'status': 'success',
        'message': f"Attendance session #{session_id} ended and archived.",
        'session': closed_session
    }), 200


@app.route('/api/reports/export-csv', methods=['GET'])
@role_required('faculty', 'admin')
def api_export_csv():
    course_id = request.args.get('course_id', 'all')
    db_path = get_db_path()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Roll Number',
        'Student Name',
        'Email',
        'Course Code',
        'Total Sessions',
        'Attended Sessions',
        'Attendance Percentage',
        'Eligibility Status'
    ])

    if course_id and course_id != 'all':
        course = resolve_course_record(course_id, db_path=db_path)
        if not course:
            return jsonify({'error': f"Course '{course_id}' not found"}), 404
        target_courses = [course]
        filename = f"attendance_report_{course['course_code']}.csv"
    else:
        dp = getattr(app, 'data_provider', data_provider)
        courses = dp.get_all_courses() if (dp and hasattr(dp, 'get_all_courses')) else CourseModel.get_all(db_path=db_path)
        target_courses = [resolve_course_record(c['course_id'], db_path=db_path) for c in courses]
        target_courses = [c for c in target_courses if c]
        filename = "attendance_report_all.csv"

    for crs in target_courses:
        rep = AttendanceService.get_course_attendance_report(crs['course_id'], db_path=db_path)
        if 'student_reports' in rep:
            course_code = crs.get('course_code') or crs['course_id']
            total_sessions = rep.get('total_sessions_held', 0)
            for sr in rep.get('student_reports', []):
                writer.writerow([
                    sr['roll_number'],
                    sr['name'],
                    sr['email'],
                    course_code,
                    total_sessions,
                    sr['attended_sessions'],
                    f"{sr['attendance_percentage']}%",
                    'Low Attendance Warning' if sr['low_attendance_warning'] else 'Eligible'
                ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


# -----------------------------------------------------------------------------
# Security & Error Handlers (Suppresses sensitive internals & stack traces)
# -----------------------------------------------------------------------------

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    if is_api_request():
        return jsonify({
            'status': 'error',
            'error': 'CSRF Error',
            'message': f"CSRF validation failed: {e.description}"
        }), 400
    from flask import flash, redirect, url_for
    flash(f"Security validation failed: {e.description}. Please try again.", "danger")
    return redirect(url_for('frontend.login'))


@app.errorhandler(403)
def handle_forbidden(e):
    if is_api_request():
        return jsonify({
            'status': 'error',
            'error': 'Forbidden',
            'message': 'Access denied: insufficient permissions.'
        }), 403
    return "Access Denied: You do not have permission to view this resource.", 403


@app.errorhandler(404)
def handle_not_found(e):
    if is_api_request():
        return jsonify({
            'status': 'error',
            'error': 'Not Found',
            'message': 'The requested resource was not found.'
        }), 404
    return "Resource Not Found", 404


@app.errorhandler(500)
def handle_internal_error(e):
    logger.exception("Unhandled server exception encountered.")
    if is_api_request():
        return jsonify({
            'status': 'error',
            'error': 'Internal Server Error',
            'message': 'An internal server error occurred.'
        }), 500
    return "An internal server error occurred.", 500


if __name__ == '__main__':
    print("\n" + "="*70)
    print(" Smart Attendance System - Frontend Presentation Tier")
    print(" Accessible at: http://127.0.0.1:5000")
    print(" Demo Login: faculty@college.edu / faculty123")
    print("="*70 + "\n")
    app.run(debug=False, use_reloader=False, host='127.0.0.1', port=5000)
