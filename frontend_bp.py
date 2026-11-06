"""
Smart Attendance System - Frontend Blueprint
Provides page routes for the presentation tier.
Integrates cleanly with the backend via:
    from frontend_bp import frontend_bp
    app.register_blueprint(frontend_bp)

Roles
-----
admin    - owns master data: registers students, creates courses, assigns teachers to course
           sections, manages rosters and captures face references.
faculty  - sees only the courses/sections they teach; starts attendance sessions for those
           sections; reviews attendance and reports.
"""

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


def _provider():
    return getattr(current_app, 'data_provider', None)


def _user():
    return session.get('user', {})


def _is_admin() -> bool:
    return str(_user().get('role', '')).lower() == 'admin'


def _scope():
    """faculty_id to scope queries to, or None for administrators (who see everything)."""
    return None if _is_admin() else _user().get('faculty_id')


def _admin_only(action: str):
    """Return 403 response when a non-admin hits an admin action; None if allowed."""
    if _is_admin():
        return None
    flash(f"Only administrators can {action}.", 'danger')
    return ("Access denied: Requires admin role.", 403)


@frontend_bp.app_context_processor
def inject_permissions():
    return {
        'is_admin': _is_admin(),
        'current_user': _user(),
    }


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
    dp = _provider()
    empty = {'stats': {'active_sessions': 0, 'total_students': 0, 'faces_enrolled': 0,
                       'total_courses': 0, 'avg_attendance': 'N/A'},
             'recent_sessions': [], 'courses': []}
    data = dp.get_dashboard_data(_scope()) if dp and hasattr(dp, 'get_dashboard_data') else empty

    assignments = []
    if dp and not _is_admin() and _user().get('faculty_id') and hasattr(dp, 'get_teaching_assignments'):
        assignments = dp.get_teaching_assignments(_user()['faculty_id'])

    return render_template(
        'dashboard.html',
        active_page='dashboard',
        stats=data.get('stats', empty['stats']),
        recent_sessions=data.get('recent_sessions', []),
        courses=data.get('courses', []),
        assignments=assignments,
    )


@frontend_bp.route('/students')
@faculty_required
def students():
    dp = _provider()
    students_list = dp.get_all_students(_scope()) if dp and hasattr(dp, 'get_all_students') else []
    courses_list = dp.get_all_courses(_scope()) if dp and hasattr(dp, 'get_all_courses') else []
    sections = dp.get_sections() if dp and hasattr(dp, 'get_sections') else []

    return render_template(
        'students.html',
        active_page='students',
        students=students_list,
        courses=courses_list,
        sections=sections or ['A', 'B', 'C'],
    )


@frontend_bp.route('/actions/students/add', methods=['POST'])
@login_required
def add_student_action():
    denied = _admin_only('register new students')
    if denied:
        return denied
    roll_no = request.form.get('roll_no', '').strip()
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    section = request.form.get('section', 'A').strip().upper() or 'A'

    if not roll_no or not name or not email:
        flash('All student fields are required.', 'danger')
        return redirect(url_for('frontend.students'))

    dp = _provider()
    if dp and hasattr(dp, 'create_student'):
        created = dp.create_student(roll_no, name, email, section=section)
        if created:
            flash(f"Student {name} ({roll_no}, Section {section}) registered and enrolled in the section's courses.", 'success')
        else:
            flash(f"Failed to register student {name} ({roll_no}).", 'danger')
    else:
        flash('Data provider unavailable.', 'danger')

    return redirect(url_for('frontend.students'))


@frontend_bp.route('/courses')
@faculty_required
def courses():
    dp = _provider()
    courses_list = dp.get_all_courses(_scope()) if dp and hasattr(dp, 'get_all_courses') else []
    faculty_list = dp.get_all_faculty() if _is_admin() and dp and hasattr(dp, 'get_all_faculty') else []
    sections = dp.get_sections() if dp and hasattr(dp, 'get_sections') else []

    return render_template(
        'courses.html',
        active_page='courses',
        courses=courses_list,
        faculty_list=faculty_list,
        sections=sections or ['A', 'B', 'C'],
    )


@frontend_bp.route('/actions/courses/create', methods=['POST'])
@login_required
def create_course_action():
    denied = _admin_only('create new courses')
    if denied:
        return denied
    code = request.form.get('code', '').strip()
    name = request.form.get('name', '').strip()
    credits_raw = request.form.get('credits', '').strip()
    semester_raw = request.form.get('semester', '').strip()
    academic_year_raw = request.form.get('academic_year', '').strip()
    faculty_id = request.form.get('faculty_id', '').strip()
    sections = [s.strip().upper() for s in request.form.getlist('sections') if s.strip()]

    if not code or not name:
        flash('Course code and course title are required.', 'danger')
        return redirect(url_for('frontend.courses'))

    dp = _provider()
    if not dp or not hasattr(dp, 'create_course'):
        flash('Course service unavailable.', 'danger')
        return redirect(url_for('frontend.courses'))

    try:
        course = dp.create_course(
            code=code,
            name=name,
            faculty_id=faculty_id,
            credits=int(credits_raw) if credits_raw else None,
            semester=int(semester_raw) if semester_raw else None,
            academic_year=academic_year_raw or None,
            sections=sections,
        )
        if course:
            flash(f"Course {code} ({name}) created. You can now assign a teacher to each section.", 'success')
        else:
            flash(f"Course {code} already exists or could not be created.", 'danger')
    except Exception as err:
        flash(f"Failed to create course: {str(err)}", 'danger')

    return redirect(url_for('frontend.courses'))


@frontend_bp.route('/actions/courses/<course_id>/sections', methods=['POST'])
@admin_required
def assign_section_action(course_id):
    """Assign (or reassign) the teacher of one section of a course; blank teacher removes the section."""
    section = request.form.get('section', '').strip().upper()
    faculty_id = request.form.get('faculty_id', '').strip()
    dp = _provider()

    if not section:
        flash('Choose a section.', 'danger')
    elif not faculty_id:
        dp.remove_section(course_id, section)
        flash(f"Section {section} removed from {course_id}. Existing enrolments were kept.", 'info')
    else:
        try:
            dp.assign_section(course_id, section, faculty_id, enroll_students=True)
            flash(f"Section {section} of {course_id} assigned and its students enrolled.", 'success')
        except Exception as err:
            flash(f"Could not assign section: {err}", 'danger')
    return redirect(url_for('frontend.courses'))


@frontend_bp.route('/actions/sessions/start', methods=['POST'])
@faculty_required
def start_session_action():
    course_id = request.form.get('course_id')
    topic = request.form.get('topic', '').strip()
    section = request.form.get('section', '').strip().upper()

    dp = _provider()
    if not dp or not hasattr(dp, 'start_session'):
        flash('Attendance service unavailable.', 'danger')
        return redirect(url_for('frontend.dashboard'))

    faculty_id = _user().get('faculty_id')
    if _is_admin() or not faculty_id:
        flash('Attendance sessions are started by the teacher assigned to the section.', 'warning')
        return redirect(url_for('frontend.dashboard'))
    if not course_id or not section:
        flash('Select a course and a section to start a session.', 'danger')
        return redirect(url_for('frontend.dashboard'))

    try:
        session_id = dp.start_session(course_id, topic, faculty_id=faculty_id, section=section)
        flash('Attendance session started. Switch on the camera to begin scanning.', 'info')
        return redirect(url_for('frontend.session_view', session_id=session_id))
    except Exception as err:
        flash(f"Failed to start session: {str(err)}", 'danger')
        return redirect(url_for('frontend.dashboard'))


@frontend_bp.route('/sessions/<session_id>')
@faculty_required
def session_view(session_id):
    dp = _provider()
    if not dp:
        flash('Data provider unavailable.', 'danger')
        return redirect(url_for('frontend.dashboard'))

    session_data = dp.get_session_details(session_id)
    if not session_data:
        flash(f"Session '{session_id}' not found.", 'danger')
        return redirect(url_for('frontend.dashboard'))

    if not _is_admin() and session_data.get('faculty_id') != _user().get('faculty_id'):
        flash("Access denied: You are not authorized to view another instructor's session.", 'danger')
        return redirect(url_for('frontend.dashboard'))

    return render_template(
        'session.html',
        active_page='dashboard',
        session_data=session_data,
        enrolled_students=dp.get_enrolled_students_for_session(session_id),
        attendance_records=dp.get_attendance_records(session_id),
    )


@frontend_bp.route('/reports')
@faculty_required
def reports():
    course_id = request.args.get('course_id') or None
    section = request.args.get('section') or None
    session_id = request.args.get('session_id') or None
    dp = _provider()

    session_report = None
    if dp and session_id and hasattr(dp, 'get_session_report'):
        session_report = dp.get_session_report(session_id)
        if session_report:
            owner = session_report['session'].get('faculty_id')
            if not _is_admin() and owner != _user().get('faculty_id'):
                flash("Access denied: that session belongs to another instructor.", 'danger')
                return redirect(url_for('frontend.reports'))
            course_id = course_id or session_report['session']['course_id']

    if dp and hasattr(dp, 'get_reports_data'):
        data = dp.get_reports_data(course_id, section, faculty_id=_scope())
    else:
        data = {'courses': [], 'sections': [], 'student_reports': [], 'session_logs': [],
                'summary': {'total_sessions': 0, 'total_students': 0, 'eligible_count': 0, 'warning_count': 0}}

    return render_template(
        'reports.html',
        active_page='reports',
        courses=data['courses'],
        sections=data.get('sections', []),
        selected_course_id=course_id,
        selected_section=(section or '').upper() or None,
        student_reports=data['student_reports'],
        session_logs=data['session_logs'],
        report_summary=data['summary'],
        session_report=session_report,
    )
