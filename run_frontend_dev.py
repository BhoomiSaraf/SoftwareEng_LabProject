"""
Smart Attendance System - Frontend Development Server & Mock API Engine
Enables complete independent testing and demonstration of the presentation tier,
interactive camera recognition pipeline, duplicate prevention, and CSV export.
"""

import io
import csv
import datetime
from flask import Flask, jsonify, request, Response
from frontend_bp import frontend_bp

app = Flask(__name__)
app.secret_key = 'smart-attendance-dev-secret-key-2026'

# Register Frontend Blueprint
app.register_blueprint(frontend_bp)

# In-memory Mock Store for Dev Demonstrations
students_store = [
    {'id': 1, 'roll_no': '21BCE001', 'name': 'Aarav Sharma', 'email': 'aarav.s@college.edu', 'has_face': True, 'course_codes': ['CS301', 'CS304']},
    {'id': 2, 'roll_no': '21BCE002', 'name': 'Aditi Patel', 'email': 'aditi.p@college.edu', 'has_face': True, 'course_codes': ['CS301']},
    {'id': 3, 'roll_no': '21BCE003', 'name': 'Alex Morgan', 'email': 'alex.m@college.edu', 'has_face': True, 'course_codes': ['CS301', 'CS304', 'CS306']},
    {'id': 4, 'roll_no': '21BCE004', 'name': 'Bhoomi Saraf', 'email': 'bhoomi.s@college.edu', 'has_face': True, 'course_codes': ['CS301', 'CS306']},
    {'id': 5, 'roll_no': '21BCE005', 'name': 'Chirag Dave', 'email': 'chirag.d@college.edu', 'has_face': False, 'course_codes': ['CS304']},
    {'id': 6, 'roll_no': '21BCE006', 'name': 'Divya Nair', 'email': 'divya.n@college.edu', 'has_face': True, 'course_codes': ['CS301', 'CS304']},
]

courses_store = [
    {'id': 1, 'code': 'CS301', 'name': 'Software Engineering Lab', 'faculty_name': 'Dr. Alan Turing', 'enrolled_student_ids': [1, 2, 3, 4, 6]},
    {'id': 2, 'code': 'CS304', 'name': 'Machine Learning', 'faculty_name': 'Dr. Alan Turing', 'enrolled_student_ids': [1, 3, 5, 6]},
    {'id': 3, 'code': 'CS306', 'name': 'Operating Systems', 'faculty_name': 'Dr. Alan Turing', 'enrolled_student_ids': [3, 4]},
]

# Track marked student IDs per session: { session_id: set(student_ids) }
session_attendance_store = {
    101: {1, 2, 3}  # 1, 2, 3 already marked
}

recognition_scan_cycle = 0


# Mock API Endpoints
@app.route('/api/students/<int:student_id>/register-face', methods=['POST'])
def api_register_face(student_id):
    data = request.get_json(silent=True) or {}
    image_data = data.get('image')
    if not image_data:
        return jsonify({'error': 'No image data payload received'}), 400

    student = next((s for s in students_store if s['id'] == student_id), None)
    if not student:
        return jsonify({'error': 'Student not found'}), 404

    student['has_face'] = True
    student['face_samples_count'] = 1
    return jsonify({
        'status': 'success',
        'message': f"Face embeddings computed and linked for {student['name']} ({student['roll_no']})."
    })


@app.route('/api/courses/<int:course_id>/enrollment-data', methods=['GET'])
def api_course_enrollment_data(course_id):
    course = next((c for c in courses_store if c['id'] == course_id), None)
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    return jsonify({
        'course_id': course_id,
        'course_code': course['code'],
        'students': students_store,
        'enrolled_ids': course.get('enrolled_student_ids', [])
    })


@app.route('/api/courses/<int:course_id>/enroll', methods=['POST'])
def api_enroll_course(course_id):
    data = request.get_json(silent=True) or {}
    student_ids = [int(sid) for sid in data.get('student_ids', [])]

    course = next((c for c in courses_store if c['id'] == course_id), None)
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    course['enrolled_student_ids'] = student_ids
    return jsonify({
        'status': 'success',
        'message': f"Enrolled {len(student_ids)} students in {course['code']}."
    })


@app.route('/api/sessions/<int:session_id>/recognize', methods=['POST'])
def api_recognize(session_id):
    global recognition_scan_cycle
    data = request.get_json(silent=True) or {}
    image = data.get('image')

    if not image:
        return jsonify({'error': 'Missing frame image data'}), 400

    if session_id not in session_attendance_store:
        session_attendance_store[session_id] = set()

    marked_set = session_attendance_store[session_id]

    # Cycle demonstration for testing:
    # 1. Unmarked student -> Marked
    # 2. Rescan of same student -> Duplicate rejected (already_marked)
    # 3. Not enrolled student -> Not enrolled
    # 4. Unknown face
    recognition_scan_cycle += 1
    cycle_index = recognition_scan_cycle % 4

    if cycle_index == 1:
        # Candidate 4: Bhoomi Saraf (Enrolled, not marked yet)
        candidate = next((s for s in students_store if s['id'] == 4), None)
        if candidate['id'] in marked_set:
            return jsonify({
                'status': 'already_marked',
                'student': candidate,
                'message': f"Student {candidate['name']} ({candidate['roll_no']}) has already been recorded for this session."
            })
        marked_set.add(candidate['id'])
        return jsonify({
            'status': 'marked',
            'student': candidate,
            'timestamp': datetime.datetime.now().strftime('%I:%M:%S %p'),
            'method': 'FACE_RECOGNITION'
        })
    elif cycle_index == 2:
        # Duplicate scan of Aarav Sharma (already marked)
        candidate = next((s for s in students_store if s['id'] == 1), None)
        return jsonify({
            'status': 'already_marked',
            'student': candidate,
            'message': f"Student {candidate['name']} ({candidate['roll_no']}) is already marked present in session #{session_id}."
        })
    elif cycle_index == 3:
        # Chirag Dave (Not enrolled in CS301)
        candidate = next((s for s in students_store if s['id'] == 5), None)
        return jsonify({
            'status': 'not_enrolled',
            'student': candidate,
            'message': f"{candidate['name']} is recognized but not enrolled in this course roster."
        })
    else:
        # Unrecognized face
        return jsonify({
            'status': 'unrecognized',
            'message': 'Face detected but does not match any registered student embeddings.'
        })


@app.route('/api/sessions/<int:session_id>/mark-manual', methods=['POST'])
def api_mark_manual(session_id):
    data = request.get_json(silent=True) or {}
    student_id = int(data.get('student_id', 0))

    student = next((s for s in students_store if s['id'] == student_id), None)
    if not student:
        return jsonify({'error': 'Student not found'}), 404

    if session_id not in session_attendance_store:
        session_attendance_store[session_id] = set()

    marked_set = session_attendance_store[session_id]
    if student_id in marked_set:
        return jsonify({
            'status': 'already_marked',
            'student': student,
            'message': f"{student['name']} ({student['roll_no']}) is already marked present for this session."
        })

    marked_set.add(student_id)
    return jsonify({
        'status': 'marked',
        'student': student,
        'timestamp': datetime.datetime.now().strftime('%I:%M:%S %p'),
        'method': 'MANUAL'
    })


@app.route('/api/sessions/<int:session_id>/end', methods=['POST'])
def api_end_session(session_id):
    return jsonify({
        'status': 'success',
        'message': f"Attendance session #{session_id} ended and archived."
    })


@app.route('/api/reports/export-csv', methods=['GET'])
def api_export_csv():
    course_id = request.args.get('course_id', 'all')

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

    sample_report = [
        ('21BCE001', 'Aarav Sharma', 'aarav.s@college.edu', 'CS301', 4, 4, '100%', 'Eligible'),
        ('21BCE002', 'Aditi Patel', 'aditi.p@college.edu', 'CS301', 4, 3, '75%', 'Eligible'),
        ('21BCE003', 'Alex Morgan', 'alex.m@college.edu', 'CS301', 4, 4, '100%', 'Eligible'),
        ('21BCE004', 'Bhoomi Saraf', 'bhoomi.s@college.edu', 'CS301', 4, 4, '100%', 'Eligible'),
        ('21BCE005', 'Chirag Dave', 'chirag.d@college.edu', 'CS301', 4, 2, '50%', 'Low Attendance Warning'),
        ('21BCE006', 'Divya Nair', 'divya.n@college.edu', 'CS301', 4, 3, '75%', 'Eligible'),
    ]

    for row in sample_report:
        writer.writerow(row)

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=attendance_report_course_{course_id}.csv'}
    )


if __name__ == '__main__':
    print("\n" + "="*70)
    print(" Smart Attendance System - Frontend Presentation Tier")
    print(" Accessible at: http://127.0.0.1:5000")
    print(" Demo Login: faculty@college.edu / faculty123")
    print("="*70 + "\n")
    app.run(debug=True, host='127.0.0.1', port=5000)
