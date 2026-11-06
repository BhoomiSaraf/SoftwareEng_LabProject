"""
Smart Attendance System - Frontend & role/section behaviour tests.

Every test runs on a throw-away database built from the demo seed file, so nothing here depends on
(or modifies) the developer's real smart_attendance.db.
"""

import json
import os
import re

import pytest

import database
import seed_demo
from data_provider import DataProvider
from face_recognition_service import face_service
from run_frontend_dev import app

ADMIN = {'id': 1, 'name': 'Administrator', 'role': 'admin'}


def faculty_user(faculty_id, name='Teacher'):
    return {'id': 2, 'name': name, 'role': 'faculty', 'faculty_id': faculty_id}


@pytest.fixture
def env(tmp_path):
    db_file = str(tmp_path / 'frontend.db')
    emb_file = str(tmp_path / 'emb.npz')
    database.init_db(db_file)

    data = json.load(open(seed_demo.SEED_FILE, encoding='utf-8'))
    for st in data['students']:
        st.pop('photo', None)          # no biometrics needed for UI tests
    conn = database.get_db_connection(db_file)
    seed_demo.seed(conn, data)
    conn.close()

    face_service.clear_registry()
    orig = (app.config.get('DB_PATH'), app.config.get('EMBEDDINGS_FILE'), getattr(app, 'data_provider', None))
    app.config.update(TESTING=True, DB_PATH=db_file, EMBEDDINGS_FILE=emb_file)
    dp = DataProvider(db_path=db_file, embeddings_path=emb_file)
    app.data_provider = dp
    client = app.test_client()
    token = re.search(r'name="csrf-token" content="([^"]+)"', client.get('/login').data.decode()).group(1)
    client.environ_base['HTTP_X_CSRFTOKEN'] = token

    def login(user):
        with client.session_transaction() as sess:
            sess['user'] = user

    yield {'client': client, 'dp': dp, 'db': db_file, 'login': login, 'csrf': token}

    face_service.clear_registry()
    app.config['DB_PATH'], app.config['EMBEDDINGS_FILE'], app.data_provider = orig


def start_session(env, faculty_id, course='CRS-CSE3132', section='A'):
    env['login'](faculty_user(faculty_id))
    r = env['client'].post('/actions/sessions/start', data={'course_id': course, 'section': section, 'csrf_token': env['csrf']})
    assert r.status_code == 302, r.data
    return r.headers['Location'].rsplit('/', 1)[-1]


# ----------------------------------------------------------------- pages / roles

def test_unauthenticated_redirect(env):
    r = env['client'].get('/dashboard')
    assert r.status_code == 302 and '/login' in r.headers['Location']


def test_login_page_has_no_prefilled_credentials(env):
    html = env['client'].get('/login').data.decode()
    assert 'Sign In' in html
    assert 'value="faculty123"' not in html and 'MVP' not in html


def test_login_with_seeded_faculty(env):
    r = env['client'].post('/login', data={'username': 'rajesh.kumar', 'password': 'faculty123', 'csrf_token': env['csrf']},
                           follow_redirects=True)
    assert b'Faculty Dashboard' in r.data


def test_mvp_badge_removed_from_every_page(env):
    env['login'](ADMIN)
    for url in ('/dashboard', '/students', '/courses', '/reports'):
        assert b'MVP' not in env['client'].get(url).data


def test_admin_sees_admin_controls(env):
    env['login'](ADMIN)
    assert b'Admin Console' in env['client'].get('/dashboard').data
    assert b'Create New Course' in env['client'].get('/courses').data
    students = env['client'].get('/students').data
    assert b'Register New Student' in students and b'Capture Face' in students


def test_faculty_has_no_admin_controls(env):
    env['login'](faculty_user('FAC001'))
    courses = env['client'].get('/courses').data
    assert b'Create New Course' not in courses and b'assign-teachers-btn' not in courses
    students = env['client'].get('/students').data
    assert b'Register New Student' not in students
    assert b'Capture Face' not in students and b'faceEnrollModal' not in students


def test_faculty_only_sees_own_courses_and_students(env):
    # FAC001 teaches CSE3132 (A, C) and CSE3113 (C); never CSE3109 (FAC006 only)
    env['login'](faculty_user('FAC001'))
    html = env['client'].get('/courses').data.decode()
    assert 'CSE3132' in html and 'CSE3113' in html
    assert 'CSE3109' not in html
    names = {s['name'] for s in env['dp'].get_all_students('FAC001')}
    assert 'Bhoomi Saraf' in names and 'Priya Patel' not in names      # Priya is section B only


def test_faculty_cannot_create_course_or_student(env):
    env['login'](faculty_user('FAC001'))
    c = env['client']
    r = c.post('/actions/courses/create', data={'code': 'X1', 'name': 'x', 'faculty_id': 'FAC001', 'csrf_token': env['csrf']})
    assert r.status_code == 403
    r = c.post('/actions/students/add', data={'roll_no': '1', 'name': 'n', 'email': 'e@x.com', 'csrf_token': env['csrf']})
    assert r.status_code == 403
    r = c.post('/actions/courses/CRS-CSE3132/sections', data={'section': 'A', 'faculty_id': 'FAC001', 'csrf_token': env['csrf']})
    assert r.status_code == 403


def test_admin_roster_and_face_apis_are_admin_only(env):
    env['login'](faculty_user('FAC001'))
    c = env['client']
    assert c.post('/api/courses/CRS-CSE3132/enroll', json={'student_ids': []}).status_code == 403
    assert c.post('/api/students/STU001/register-face', json={'image': 'x'}).status_code == 403


# ----------------------------------------------------------------- admin master data

def test_admin_creates_course_with_sections_and_enrols_them(env):
    env['login'](ADMIN)
    r = env['client'].post('/actions/courses/create', data={
        'code': 'CSE3999', 'name': 'Prototype Studio', 'faculty_id': 'FAC002', 'credits': '3',
        'sections': ['A', 'B'], 'csrf_token': env['csrf']}, follow_redirects=True)
    assert b'created' in r.data
    course = next(c for c in env['dp'].get_all_courses() if c['code'] == 'CSE3999')
    assert {s['section'] for s in course['sections']} == {'A', 'B'}
    assert all(s['faculty_id'] == 'FAC002' for s in course['sections'])
    assert course['enrolled_count'] == 19          # 10 in A + 9 in B, none from C


def test_admin_reassigns_section_teacher(env):
    env['login'](ADMIN)
    env['client'].post('/actions/courses/CRS-CSE3132/sections',
                       data={'section': 'A', 'faculty_id': 'FAC005', 'csrf_token': env['csrf']})
    course = next(c for c in env['dp'].get_all_courses() if c['code'] == 'CSE3132')
    assert {s['section']: s['faculty_id'] for s in course['sections']}['A'] == 'FAC005'
    # the previous teacher (FAC001) can no longer start section A, but still has C
    env['login'](faculty_user('FAC001'))
    r = env['client'].post('/actions/sessions/start',
                           data={'course_id': 'CRS-CSE3132', 'section': 'A', 'csrf_token': env['csrf']}, follow_redirects=True)
    assert b'not authorized to start session' in r.data


def test_new_student_is_enrolled_in_their_sections_courses(env):
    s = env['dp'].create_student('229309999', 'New Joiner', 'new@muj.manipal.edu', section='B')
    codes = set(env['dp'].get_student_by_id(s['student_id'])['course_codes'])
    assert 'CSE3132' in codes and 'CSE3111' in codes       # B courses
    assert 'CSE3115' not in codes                          # Data Mining Lab runs for A and C only


# ----------------------------------------------------------------- sessions by section

def test_session_roster_is_the_chosen_section_only(env):
    sid = start_session(env, 'FAC001', section='A')
    roster = env['dp'].get_enrolled_students_for_session(sid)
    assert len(roster) == 10 and {s['section'] for s in roster} == {'A'}
    assert 'Bhoomi Saraf' in {s['name'] for s in roster}


def test_faculty_cannot_start_unassigned_section(env):
    env['login'](faculty_user('FAC001'))
    r = env['client'].post('/actions/sessions/start',
                           data={'course_id': 'CRS-CSE3132', 'section': 'B', 'csrf_token': env['csrf']}, follow_redirects=True)
    assert b'not authorized to start session' in r.data


def test_admin_cannot_start_sessions(env):
    env['login'](ADMIN)
    r = env['client'].post('/actions/sessions/start',
                           data={'course_id': 'CRS-CSE3132', 'section': 'A', 'csrf_token': env['csrf']}, follow_redirects=True)
    assert b'started by the teacher assigned' in r.data


def test_manual_mark_rejects_other_section_and_duplicates(env):
    sid = start_session(env, 'FAC001', section='A')
    c = env['client']
    ok = c.post(f'/api/sessions/{sid}/mark-manual', json={'student_id': 'STU001'}).get_json()
    assert ok['status'] == 'marked'
    again = c.post(f'/api/sessions/{sid}/mark-manual', json={'student_id': 'STU001'}).get_json()
    assert again['status'] == 'already_marked'
    other = env['dp'].get_all_students()
    sec_b = next(s for s in other if s['section'] == 'B')
    wrong = c.post(f'/api/sessions/{sid}/mark-manual', json={'student_id': sec_b['student_id']}).get_json()
    assert wrong['status'] == 'wrong_section'


def test_live_session_page_config_is_valid_javascript(env):
    """Regression: the session id used to be emitted unquoted, which killed the whole scanner script."""
    sid = start_session(env, 'FAC001', section='A')
    html = env['client'].get(f'/sessions/{sid}').data.decode()
    assert f'sessionId: {json.dumps(sid)},' in html          # a quoted JS string, not a bare identifier
    assert 'courseId: "CRS-CSE3132",' in html
    assert 'Section: A' in html


def test_faculty_cannot_open_another_teachers_session(env):
    sid = start_session(env, 'FAC001', section='A')
    env['login'](faculty_user('FAC002'))
    r = env['client'].get(f'/sessions/{sid}', follow_redirects=True)
    assert b'not authorized to view another instructor' in r.data


# ----------------------------------------------------------------- reports

def test_report_percentages_are_per_section(env):
    sid_a = start_session(env, 'FAC001', section='A')
    c = env['client']
    c.post(f'/api/sessions/{sid_a}/mark-manual', json={'student_id': 'STU001'})
    c.post(f'/api/sessions/{sid_a}/end')
    rep = env['dp'].get_reports_data('CRS-CSE3132', faculty_id='FAC001')
    by_stu = {r['student_id']: r for r in rep['student_reports']}
    assert by_stu['STU001']['percentage'] == 100.0                     # attended the only A session
    sec_a_other = next(r for r in rep['student_reports'] if r['section'] == 'A' and r['student_id'] != 'STU001')
    assert sec_a_other['percentage'] == 0.0
    sec_c = next(r for r in rep['student_reports'] if r['section'] == 'C')
    assert sec_c['total_sessions'] == 0 and sec_c['percentage'] is None  # no C session yet: N/A, not 100%


def test_session_report_lists_present_and_absent(env):
    sid = start_session(env, 'FAC001', section='A')
    env['client'].post(f'/api/sessions/{sid}/mark-manual', json={'student_id': 'STU001'})
    rep = env['dp'].get_session_report(sid)
    assert [s['student_id'] for s in rep['present']] == ['STU001'] and len(rep['absent']) == 9
    env['login'](faculty_user('FAC001'))
    assert b'Session report' in env['client'].get(f'/reports?session_id={sid}').data


def test_csv_export_is_scoped_to_the_teacher(env):
    env['login'](faculty_user('FAC001'))
    text = env['client'].get('/api/reports/export-csv?course_id=all').data.decode()
    assert 'CSE3132' in text and 'CSE3109' not in text
    assert env['client'].get('/api/reports/export-csv?course_id=CRS-CSE3109').status_code == 404
