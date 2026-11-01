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
from auth import AuthService, faculty_required, admin_required, login_required

frontend_bp = Blueprint('frontend', __name__, template_folder='templates', static_folder='static')


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

        if not username or not password:
            flash('Both username and password are required.', 'danger')
            return render_template('login.html', active_page='login')

        auth_service = getattr(current_app, 'auth_service', None) or AuthService
        user_info = auth_service.authenticate(username, password)

        if user_info:
            session.clear()
            session['user'] = user_info
            flash(f"Welcome back, {user_info.get('name', 'Faculty')}!", 'success')
            return redirect(url_for('frontend.dashboard'))
        else:
            flash('Invalid username or password. Please verify your credentials.', 'danger')

    return render_template('login.html', active_page='login')


@frontend_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out securely.', 'info')
    return redirect(url_for('frontend.login'))


@frontend_bp.route('/dashboard')
@faculty_required
def dashboard():
    data_provider = getattr(current_app, 'data_provider', None)

    if data_provider and hasattr(data_provider, 'get_dashboard_data'):
        data = data_provider.get_dashboard_data()
        stats = data.get('stats', {'active_sessions': 0, 'total_students': 0, 'total_courses': 0, 'avg_attendance': '0.0%'})
        recent_sessions = data.get('recent_sessions', [])
        courses = data.get('courses', [])
    else:
        stats = {'active_sessions': 0, 'total_students': 0, 'total_courses': 0, 'avg_attendance': '0.0%'}
        recent_sessions = []
        courses = []

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
        students_list = []

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
        created = data_provider.create_student(roll_no, name, email)
        if created:
            flash(f"Student {name} ({roll_no}) registered successfully.", 'success')
        else:
            flash(f"Failed to register student {name} ({roll_no}).", 'danger')
    else:
        flash('Data provider unavailable.', 'danger')

    return redirect(url_for('frontend.students'))


@frontend_bp.route('/courses')
@faculty_required
def courses():
    data_provider = getattr(current_app, 'data_provider', None)
    if data_provider and hasattr(data_provider, 'get_all_courses'):
        courses_list = data_provider.get_all_courses()
    else:
        courses_list = []

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
        course = data_provider.create_course(code, name, description)
        if course:
            flash(f"Course {code} ({name}) created successfully.", 'success')
        else:
            flash(f"Course {code} already exists or could not be created.", 'danger')
    else:
        flash('Course service unavailable.', 'danger')

    return redirect(url_for('frontend.courses'))


@frontend_bp.route('/actions/sessions/start', methods=['POST'])
@faculty_required
def start_session_action():
    course_id = request.form.get('course_id')
    topic = request.form.get('topic', '').strip()

    data_provider = getattr(current_app, 'data_provider', None)
    if not data_provider or not hasattr(data_provider, 'start_session'):
        flash('Attendance service unavailable.', 'danger')
        return redirect(url_for('frontend.dashboard'))

    # Verify instructor assignment for this course
    user = session.get('user', {})
    user_faculty_id = user.get('faculty_id')
    user_role = str(user.get('role', '')).lower()

    if user_role != 'admin' and user_faculty_id:
        import database
        db_path = getattr(data_provider, 'db_path', None)
        with database.get_db_cursor(db_path, commit=False) as cursor:
            cursor.execute(
                "SELECT faculty_id FROM courses WHERE course_id = ? OR course_code = ?;",
                (course_id, course_id)
            )
            c_row = cursor.fetchone()
            if c_row and c_row['faculty_id'] != user_faculty_id:
                flash("Access denied: You are not assigned to instruct this course.", 'danger')
                return redirect(url_for('frontend.dashboard'))

    try:
        session_id = data_provider.start_session(course_id, topic, faculty_id=user_faculty_id)
        flash('Attendance session initialized. Starting optical camera scanner.', 'info')
        return redirect(url_for('frontend.session_view', session_id=session_id))
    except Exception as err:
        flash(f"Failed to start session: {str(err)}", 'danger')
        return redirect(url_for('frontend.dashboard'))


@frontend_bp.route('/sessions/<session_id>')
@faculty_required
def session_view(session_id):
    data_provider = getattr(current_app, 'data_provider', None)
    if not data_provider:
        flash('Data provider unavailable.', 'danger')
        return redirect(url_for('frontend.dashboard'))

    session_data = data_provider.get_session_details(session_id)
    if not session_data:
        flash(f"Session '{session_id}' not found.", 'danger')
        return redirect(url_for('frontend.dashboard'))

    user = session.get('user', {})
    user_faculty_id = user.get('faculty_id')
    user_role = str(user.get('role', '')).lower()

    if user_role != 'admin' and user_faculty_id and session_data.get('faculty_id'):
        if session_data['faculty_id'] != user_faculty_id:
            flash("Access denied: You are not authorized to view another instructor's session.", 'danger')
            return redirect(url_for('frontend.dashboard'))

    enrolled_students = data_provider.get_enrolled_students_for_session(session_id)
    attendance_records = data_provider.get_attendance_records(session_id)

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
        report_summary = reports_data.get('summary', {'total_sessions': 0, 'total_students': 0, 'eligible_count': 0, 'warning_count': 0})
    else:
        courses = []
        student_reports = []
        session_logs = []
        report_summary = {'total_sessions': 0, 'total_students': 0, 'eligible_count': 0, 'warning_count': 0}

    return render_template(
        'reports.html',
        active_page='reports',
        courses=courses,
        selected_course_id=int(course_id) if course_id and course_id.isdigit() else (course_id if course_id else None),
        student_reports=student_reports,
        session_logs=session_logs,
        report_summary=report_summary
    )
