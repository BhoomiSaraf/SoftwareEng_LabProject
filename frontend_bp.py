"""
Smart Attendance System - Frontend Blueprint
Provides page routes for the presentation tier.
Integrates cleanly with the backend via:
    from frontend_bp import frontend_bp
    app.register_blueprint(frontend_bp)
"""

from functools import wraps
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    current_app,
)

frontend_bp = Blueprint('frontend', __name__, template_folder='templates', static_folder='static')


def faculty_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please log in with faculty credentials to access this portal.', 'warning')
            return redirect(url_for('frontend.login'))
        return f(*args, **kwargs)
    return decorated_function


@frontend_bp.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('frontend.dashboard'))
    return redirect(url_for('frontend.login'))


@frontend_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        # Check credentials via configured auth service or standard dev fallback
        auth_service = getattr(current_app, 'auth_service', None)
        authenticated = False
        user_info = None

        if auth_service and hasattr(auth_service, 'authenticate'):
            user_info = auth_service.authenticate(username, password)
            authenticated = bool(user_info)
        else:
            # Standard development authentication fallback
            if username and password:
                authenticated = True
                user_info = {
                    'id': 1,
                    'name': 'Dr. Alan Turing',
                    'email': username,
                    'role': 'Faculty'
                }

        if authenticated:
            session['user'] = user_info
            flash(f"Welcome back, {user_info.get('name', 'Faculty')}!", 'success')
            return redirect(url_for('frontend.dashboard'))
        else:
            flash('Invalid username or password. Please verify your credentials.', 'danger')

    return render_template('login.html', active_page='login')


@frontend_bp.route('/logout')
def logout():
    session.pop('user', None)
    flash('You have been logged out securely.', 'info')
    return redirect(url_for('frontend.login'))


@frontend_bp.route('/dashboard')
@faculty_required
def dashboard():
    data_provider = getattr(current_app, 'data_provider', None)

    if data_provider and hasattr(data_provider, 'get_dashboard_data'):
        data = data_provider.get_dashboard_data()
        stats = data.get('stats', {})
        recent_sessions = data.get('recent_sessions', [])
        courses = data.get('courses', [])
    else:
        # Default presentation state
        stats = {
            'active_sessions': 1,
            'total_students': 24,
            'total_courses': 3,
            'avg_attendance': '87.5%'
        }
        recent_sessions = [
            {
                'id': 101,
                'course_code': 'CS301',
                'course_name': 'Software Engineering Lab',
                'date': '2026-10-27',
                'start_time': '09:00 AM',
                'status': 'ACTIVE',
                'present_count': 18,
                'total_enrolled': 24,
                'attendance_percentage': 75
            },
            {
                'id': 100,
                'course_code': 'CS304',
                'course_name': 'Machine Learning',
                'date': '2026-10-26',
                'start_time': '11:00 AM',
                'status': 'COMPLETED',
                'present_count': 22,
                'total_enrolled': 24,
                'attendance_percentage': 92
            }
        ]
        courses = [
            {'id': 1, 'code': 'CS301', 'name': 'Software Engineering Lab', 'enrolled_count': 24},
            {'id': 2, 'code': 'CS304', 'name': 'Machine Learning', 'enrolled_count': 24},
            {'id': 3, 'code': 'CS306', 'name': 'Operating Systems', 'enrolled_count': 22}
        ]

    return render_template(
        'dashboard.html',
        active_page='dashboard',
        stats=stats,
        recent_sessions=recent_sessions,
        courses=courses
    )


@frontend_bp.route('/students')
@faculty_required
def students():
    data_provider = getattr(current_app, 'data_provider', None)
    if data_provider and hasattr(data_provider, 'get_all_students'):
        students_list = data_provider.get_all_students()
    else:
        students_list = [
            {'id': 1, 'roll_no': '21BCE001', 'name': 'Aarav Sharma', 'email': 'aarav.s@college.edu', 'has_face': True, 'face_samples_count': 1, 'course_codes': ['CS301', 'CS304']},
            {'id': 2, 'roll_no': '21BCE002', 'name': 'Aditi Patel', 'email': 'aditi.p@college.edu', 'has_face': True, 'face_samples_count': 1, 'course_codes': ['CS301']},
            {'id': 3, 'roll_no': '21BCE003', 'name': 'Alex Morgan', 'email': 'alex.m@college.edu', 'has_face': True, 'face_samples_count': 1, 'course_codes': ['CS301', 'CS304', 'CS306']},
            {'id': 4, 'roll_no': '21BCE004', 'name': 'Bhoomi Saraf', 'email': 'bhoomi.s@college.edu', 'has_face': True, 'face_samples_count': 1, 'course_codes': ['CS301', 'CS306']},
            {'id': 5, 'roll_no': '21BCE005', 'name': 'Chirag Dave', 'email': 'chirag.d@college.edu', 'has_face': False, 'face_samples_count': 0, 'course_codes': ['CS304']},
            {'id': 6, 'roll_no': '21BCE006', 'name': 'Divya Nair', 'email': 'divya.n@college.edu', 'has_face': True, 'face_samples_count': 1, 'course_codes': ['CS301', 'CS304']},
        ]

    return render_template('students.html', active_page='students', students=students_list)


@frontend_bp.route('/actions/students/add', methods=['POST'])
@faculty_required
def add_student_action():
    roll_no = request.form.get('roll_no', '').strip()
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()

    if not roll_no or not name or not email:
        flash('All student fields are required.', 'danger')
        return redirect(url_for('frontend.students'))

    data_provider = getattr(current_app, 'data_provider', None)
    if data_provider and hasattr(data_provider, 'create_student'):
        data_provider.create_student(roll_no, name, email)
    
    flash(f"Student {name} ({roll_no}) registered successfully.", 'success')
    return redirect(url_for('frontend.students'))


@frontend_bp.route('/courses')
@faculty_required
def courses():
    data_provider = getattr(current_app, 'data_provider', None)
    if data_provider and hasattr(data_provider, 'get_all_courses'):
        courses_list = data_provider.get_all_courses()
    else:
        courses_list = [
            {'id': 1, 'code': 'CS301', 'name': 'Software Engineering Lab', 'faculty_name': 'Dr. Alan Turing', 'enrolled_count': 24, 'sessions_count': 4, 'description': 'Biometric facial recognition attendance MVP laboratory project.'},
            {'id': 2, 'code': 'CS304', 'name': 'Machine Learning', 'faculty_name': 'Dr. Alan Turing', 'enrolled_count': 24, 'sessions_count': 6, 'description': 'Supervised learning, deep neural networks, and pattern recognition.'},
            {'id': 3, 'code': 'CS306', 'name': 'Operating Systems', 'faculty_name': 'Dr. Alan Turing', 'enrolled_count': 22, 'sessions_count': 5, 'description': 'Concurrency, process scheduling, virtualization, and file systems.'}
        ]

    return render_template('courses.html', active_page='courses', courses=courses_list)


@frontend_bp.route('/actions/courses/create', methods=['POST'])
@faculty_required
def create_course_action():
    code = request.form.get('code', '').strip()
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()

    if not code or not name:
        flash('Course code and course title are required.', 'danger')
        return redirect(url_for('frontend.courses'))

    data_provider = getattr(current_app, 'data_provider', None)
    if data_provider and hasattr(data_provider, 'create_course'):
        data_provider.create_course(code, name, description)

    flash(f"Course {code} ({name}) created successfully.", 'success')
    return redirect(url_for('frontend.courses'))


@frontend_bp.route('/actions/sessions/start', methods=['POST'])
@faculty_required
def start_session_action():
    course_id = request.form.get('course_id')
    topic = request.form.get('topic', '').strip()

    data_provider = getattr(current_app, 'data_provider', None)
    session_id = 101
    if data_provider and hasattr(data_provider, 'start_session'):
        session_id = data_provider.start_session(course_id, topic)

    flash('Attendance session initialized. Starting optical camera scanner.', 'info')
    return redirect(url_for('frontend.session_view', session_id=session_id))


@frontend_bp.route('/sessions/<int:session_id>')
@faculty_required
def session_view(session_id):
    data_provider = getattr(current_app, 'data_provider', None)

    if data_provider and hasattr(data_provider, 'get_session_details'):
        session_data = data_provider.get_session_details(session_id)
        enrolled_students = data_provider.get_enrolled_students_for_session(session_id)
        attendance_records = data_provider.get_attendance_records(session_id)
    else:
        session_data = {
            'id': session_id,
            'course_id': 1,
            'course_code': 'CS301',
            'course_name': 'Software Engineering Lab',
            'faculty_name': session.get('user', {}).get('name', 'Faculty'),
            'start_time': '09:00:00 AM',
            'status': 'ACTIVE',
            'total_enrolled': 24,
            'present_count': 3,
            'attendance_percentage': 13
        }
        enrolled_students = [
            {'id': 1, 'roll_no': '21BCE001', 'name': 'Aarav Sharma'},
            {'id': 2, 'roll_no': '21BCE002', 'name': 'Aditi Patel'},
            {'id': 3, 'roll_no': '21BCE003', 'name': 'Alex Morgan'},
            {'id': 4, 'roll_no': '21BCE004', 'name': 'Bhoomi Saraf'},
            {'id': 5, 'roll_no': '21BCE005', 'name': 'Chirag Dave'},
            {'id': 6, 'roll_no': '21BCE006', 'name': 'Divya Nair'}
        ]
        attendance_records = [
            {'student_id': 1, 'roll_no': '21BCE001', 'student_name': 'Aarav Sharma', 'timestamp': '09:02:14 AM', 'method': 'Face Recognition'},
            {'student_id': 2, 'roll_no': '21BCE002', 'student_name': 'Aditi Patel', 'timestamp': '09:03:05 AM', 'method': 'Face Recognition'},
            {'student_id': 3, 'roll_no': '21BCE003', 'student_name': 'Alex Morgan', 'timestamp': '09:04:12 AM', 'method': 'Face Recognition'}
        ]

    return render_template(
        'session.html',
        active_page='dashboard',
        session_data=session_data,
        enrolled_students=enrolled_students,
        attendance_records=attendance_records
    )


@frontend_bp.route('/reports')
@faculty_required
def reports():
    course_id = request.args.get('course_id')
    data_provider = getattr(current_app, 'data_provider', None)

    if data_provider and hasattr(data_provider, 'get_reports_data'):
        reports_data = data_provider.get_reports_data(course_id)
        courses = reports_data.get('courses', [])
        student_reports = reports_data.get('student_reports', [])
        session_logs = reports_data.get('session_logs', [])
        report_summary = reports_data.get('summary', {})
    else:
        courses = [
            {'id': 1, 'code': 'CS301', 'name': 'Software Engineering Lab'},
            {'id': 2, 'code': 'CS304', 'name': 'Machine Learning'},
            {'id': 3, 'code': 'CS306', 'name': 'Operating Systems'}
        ]
        student_reports = [
            {'student_id': 1, 'roll_no': '21BCE001', 'student_name': 'Aarav Sharma', 'course_id': 1, 'course_code': 'CS301', 'attended_sessions': 4, 'total_sessions': 4, 'percentage': 100},
            {'student_id': 2, 'roll_no': '21BCE002', 'student_name': 'Aditi Patel', 'course_id': 1, 'course_code': 'CS301', 'attended_sessions': 3, 'total_sessions': 4, 'percentage': 75},
            {'student_id': 3, 'roll_no': '21BCE003', 'student_name': 'Alex Morgan', 'course_id': 1, 'course_code': 'CS301', 'attended_sessions': 4, 'total_sessions': 4, 'percentage': 100},
            {'student_id': 4, 'roll_no': '21BCE004', 'student_name': 'Bhoomi Saraf', 'course_id': 1, 'course_code': 'CS301', 'attended_sessions': 4, 'total_sessions': 4, 'percentage': 100},
            {'student_id': 5, 'roll_no': '21BCE005', 'student_name': 'Chirag Dave', 'course_id': 1, 'course_code': 'CS301', 'attended_sessions': 2, 'total_sessions': 4, 'percentage': 50},
            {'student_id': 6, 'roll_no': '21BCE006', 'student_name': 'Divya Nair', 'course_id': 1, 'course_code': 'CS301', 'attended_sessions': 3, 'total_sessions': 4, 'percentage': 75},
        ]
        session_logs = [
            {'id': 101, 'course_code': 'CS301', 'course_name': 'Software Engineering Lab', 'date': '2026-10-27', 'start_time': '09:00 AM', 'present_count': 18, 'total_enrolled': 24, 'attendance_percentage': 75, 'status': 'ACTIVE'},
            {'id': 100, 'course_code': 'CS301', 'course_name': 'Software Engineering Lab', 'date': '2026-10-24', 'start_time': '09:00 AM', 'present_count': 23, 'total_enrolled': 24, 'attendance_percentage': 96, 'status': 'COMPLETED'},
            {'id': 99, 'course_code': 'CS301', 'course_name': 'Software Engineering Lab', 'date': '2026-10-20', 'start_time': '09:00 AM', 'present_count': 22, 'total_enrolled': 24, 'attendance_percentage': 92, 'status': 'COMPLETED'},
            {'id': 98, 'course_code': 'CS301', 'course_name': 'Software Engineering Lab', 'date': '2026-10-17', 'start_time': '09:00 AM', 'present_count': 20, 'total_enrolled': 24, 'attendance_percentage': 83, 'status': 'COMPLETED'}
        ]
        report_summary = {
            'total_sessions': 4,
            'total_students': len(student_reports),
            'eligible_count': sum(1 for s in student_reports if s['percentage'] >= 75),
            'warning_count': sum(1 for s in student_reports if s['percentage'] < 75)
        }

    return render_template(
        'reports.html',
        active_page='reports',
        courses=courses,
        selected_course_id=int(course_id) if course_id and course_id.isdigit() else None,
        student_reports=student_reports,
        session_logs=session_logs,
        report_summary=report_summary
    )
