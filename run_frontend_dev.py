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
    """Resolve a canonical student_id (e.g. STU001) or a roll number to the DB record."""
    raw_id = str(identifier).strip() if identifier is not None else ''
    if not raw_id:
        return None
    return StudentModel.get_by_id(raw_id, db_path=db_path) or StudentModel.get_by_roll(raw_id, db_path=db_path)


def format_student_payload(student):
    sid = student['student_id']
    roll = student.get('roll_number') or student.get('roll_no', '')
    return {
        'id': sid,
        'student_id': sid,
        'roll_no': roll,
        'roll_number': roll,
        'name': student['name'],
        'email': student['email'],
        'section': (student.get('section') or 'A').upper(),
    }


def resolve_course_record(course_identifier, db_path=None):
    """Resolve a course_id or course_code to its DB row."""
    c_str = str(course_identifier).strip() if course_identifier is not None else ''
    if not c_str:
        return None
    course = CourseModel.get_by_id(c_str, db_path=db_path)
    if course:
        return course
    for c in CourseModel.get_all(db_path=db_path):
        if str(c['course_code']).lower() == c_str.lower():
            return c
    return None


# Biometric Face Registration Endpoint
@app.route('/api/students/<student_id>/register-face', methods=['POST'])
@role_required('admin')
def api_register_face(student_id):
    data = request.get_json(silent=True) or {}
    images = data.get('images') or ([data['image']] if data.get('image') else [])
    if not images:
        return jsonify({'error': 'No image data payload received'}), 400
    image_data = images[0]

    db_path = get_db_path()
    student = find_canonical_student(student_id, db_path=db_path)
    if not student:
        return jsonify({'error': 'Student not found'}), 404

    # Face enrolment (YuNet detection + SFace embedding), stored under the canonical student_id only.
    # Several frames are accepted; the usable ones are all stored (more poses/lighting = steadier matching).
    results = [face_service.register_student_face(student['student_id'], img) for img in images]
    ok_results = [r for r in results if r.get('success')]
    res = ok_results[0] if ok_results else results[0]
    if not res.get('success'):
        return jsonify({
            'status': 'error',
            'error': res.get('message', 'Face registration failed.'),
            'message': res.get('message', 'Face registration failed.')
        }), 400

    # Keep the reference photo so the embedding can be rebuilt if the recognition model changes
    try:
        faces_dir = os.path.join(os.path.dirname(os.path.abspath(get_embeddings_path())), 'faces')
        os.makedirs(faces_dir, exist_ok=True)
        import cv2
        cv2.imwrite(os.path.join(faces_dir, f"{student['student_id']}.jpg"), face_service.decode_image(image_data))
    except Exception:
        logger.warning("Could not store reference photo for %s", student['student_id'])

    emb_path = get_embeddings_path()
    save_ok = face_service.save_embeddings(emb_path)
    if not save_ok or not os.path.exists(emb_path):
        return jsonify({
            'status': 'error',
            'error': 'Storage persistence failure',
            'message': 'Failed to persist face embedding to configured storage.'
        }), 500

    # Update SQLite only after storage persistence is confirmed
    StudentModel.set_face_registered(student['student_id'], True, db_path=db_path)

    return jsonify({
        'status': 'success',
        'message': f"Face registered for {student['name']} ({student['roll_number']}).",
        'embedding_dim': res.get('embedding_dim', face_service.embedding_dim),
        'samples_count': face_service.get_sample_count(student['student_id'])
    })


@app.route('/api/courses/<course_id>/enrollment-data', methods=['GET'])
@login_required
def api_course_enrollment_data(course_id):
    db_path = get_db_path()
    course = resolve_course_record(course_id, db_path=db_path)
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    all_students = data_provider.get_all_students()
    enrolled_sid_set = {s['student_id'] for s in EnrollmentModel.get_enrolled_students(course['course_id'], db_path=db_path)}

    return jsonify({
        'course_id': course['course_id'],
        'course_code': course['course_code'],
        'sections': data_provider.get_sections(),
        'students': all_students,
        'enrolled_ids': [s['student_id'] for s in all_students if s['student_id'] in enrolled_sid_set]
    })


@app.route('/api/courses/<course_id>/enroll', methods=['POST'])
@role_required('admin')
def api_enroll_course(course_id):
    data = request.get_json(silent=True) or {}
    raw_student_ids = data.get('student_ids', [])

    db_path = get_db_path()
    course = resolve_course_record(course_id, db_path=db_path)
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    # Verify course instructor ownership (admin bypasses)
    user = flask_session.get('user', {})
    if user.get('role') != 'admin' and user.get('faculty_id') and course.get('faculty_id'):
        if course['faculty_id'] != user.get('faculty_id'):
            return jsonify({
                'status': 'error',
                'error': 'Forbidden',
                'message': 'You are not authorized to modify enrollments for another instructor\'s course.'
            }), 403

    import database
    conn = database.get_db_connection(db_path)
    try:
        conn.execute("DELETE FROM enrollments WHERE course_id = ?;", (course['course_id'],))
        enrolled_count = 0
        for raw_sid in raw_student_ids:
            st = find_canonical_student(raw_sid, db_path=db_path)
            if st:
                conn.execute(
                    "INSERT OR IGNORE INTO enrollments (course_id, student_id) VALUES (?, ?);",
                    (course['course_id'], st['student_id'])
                )
                enrolled_count += 1
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'status': 'success',
        'message': f"Enrolled {enrolled_count} students in {course['course_code']}."
    })


STRONG_MATCH = 0.72          # cosine similarity that is trusted from a single scan
VOTE_WINDOW_SECONDS = 8
_recent_matches = {}         # session_id -> list of (student_id, timestamp)


def _vote_confirms(session_id, student_id, confidence):
    import time
    now = time.time()
    recent = [m for m in _recent_matches.get(session_id, []) if now - m[1] <= VOTE_WINDOW_SECONDS]
    agreed = bool(recent) and recent[-1][0] == student_id
    recent.append((student_id, now))
    _recent_matches[session_id] = recent[-4:]
    return confidence >= STRONG_MATCH or agreed


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

    # 2. Match the face against THIS session's roster only (course + section)
    rec_threshold = getattr(Config, 'RECOGNITION_THRESHOLD', None)
    roster_ids = [
        s['student_id'] for s in
        EnrollmentModel.get_enrolled_students(session['course_id'], db_path=db_path, section=session.get('section'))
    ]
    try:
        match_result = face_service.match_face(image, allowed_student_ids=roster_ids, threshold=rec_threshold)
        if match_result.get('status') == 'UNKNOWN_FACE':
            # Not on the roster. Is it a known student from elsewhere? Give the teacher a useful reason.
            wider = face_service.match_face(image, threshold=rec_threshold)
            if wider.get('status') == 'MATCHED':
                match_result = wider
    except Exception as e:
        logger.exception("Face recognition matching exception")
        return jsonify({'status': 'recognition_error', 'message': 'Face recognition processing failed.'}), 500

    status = match_result.get('status')

    if status == 'NO_FACE_DETECTED':
        return jsonify({
            'status': 'no_face',
            'message': match_result.get('message', 'No face detected in camera view. Position face in center frame.')
        }), 200

    elif status == 'LOW_QUALITY':
        return jsonify({'status': 'low_quality', 'message': match_result.get('message', 'Image quality too low.')}), 200

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
            'message': match_result.get('message', 'Face detected but not recognised as an enrolled student.')
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

    # Agreement across scans: one frame can be a fluke, so (with the SFace engine) a student is only marked
    # when a very confident match arrives or the same student wins two scans in a row.
    if face_service.backend == 'sface' and not _vote_confirms(str(session_id), matched_id_str, confidence):
        return jsonify({
            'status': 'verifying',
            'confidence': confidence,
            'message': 'Possible match. Hold still for one more scan to confirm.'
        }), 200

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
        elif "section mismatch" in msg_lower or ("section" in msg_lower and "mismatch" in msg_lower):
            return jsonify({
                'status': 'wrong_section',
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
        elif "section mismatch" in msg_lower:
            return jsonify({
                'status': 'wrong_section',
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
    section = request.args.get('section', 'all')
    section = None if section.lower() == 'all' else section.upper()
    db_path = get_db_path()

    user = flask_session.get('user', {})
    scope = None if user.get('role') == 'admin' else user.get('faculty_id')
    dp = getattr(app, 'data_provider', data_provider)
    rep = dp.get_reports_data(None if course_id.lower() == 'all' else course_id, section, faculty_id=scope)

    if course_id.lower() != 'all' and not any(
        c['course_id'] == course_id or c['code'].lower() == course_id.lower() for c in rep['courses']
    ):
        return jsonify({'error': f"Course '{course_id}' not found"}), 404

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Roll Number', 'Student Name', 'Section', 'Course Code', 'Total Sessions',
                     'Attended Sessions', 'Attendance Percentage', 'Eligibility Status'])
    for sr in rep['student_reports']:
        pct = sr['percentage']
        writer.writerow([
            sr['roll_no'], sr['student_name'], sr['section'], sr['course_code'],
            sr['total_sessions'], sr['attended_sessions'],
            f"{pct}%" if pct is not None else 'N/A',
            'No sessions yet' if pct is None else ('Low Attendance Warning' if pct < 75.0 else 'Eligible'),
        ])

    name = 'all' if course_id.lower() == 'all' else course_id.replace('CRS-', '')
    filename = f"attendance_report_{name}{'_' + section if section else ''}.csv"
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
    print(" Seeded logins: see README (admin / admin123, faculty / faculty123)")
    print("="*70 + "\n")
    app.run(debug=False, use_reloader=False, host='127.0.0.1', port=5000)
