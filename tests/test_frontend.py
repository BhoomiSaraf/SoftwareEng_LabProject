"""
Smart Attendance System - Frontend & Reporting Test Suite
Verifies presentation routes, authentication redirects,
session screens, duplicate attendance rejection, and CSV export.
"""

import unittest
from run_frontend_dev import app


class FrontendAndReportingTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        self.client = self.app.test_client()

    def login_client(self):
        """Helper to establish faculty session"""
        with self.client.session_transaction() as sess:
            sess['user'] = {
                'id': 1,
                'name': 'Dr. Alan Turing',
                'email': 'faculty@college.edu',
                'role': 'Faculty'
            }

    def test_unauthenticated_redirect(self):
        """Unauthenticated user accessing protected route must be redirected to login"""
        response = self.client.get('/dashboard', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])

    def test_login_page_renders(self):
        """Login page renders with credential fields"""
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Faculty Portal', response.data)
        self.assertIn(b'Authenticate &amp; Enter', response.data)

    def test_login_authentication_success(self):
        """Submitting login form authenticates and redirects to dashboard"""
        response = self.client.post('/login', data={
            'username': 'faculty@college.edu',
            'password': 'faculty123'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Faculty Dashboard', response.data)

    def test_dashboard_renders(self):
        """Dashboard renders summary metric cards and active sessions"""
        self.login_client()
        response = self.client.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Active Sessions', response.data)
        self.assertIn(b'Start Attendance Session', response.data)
        self.assertIn(b'CS301', response.data)

    def test_students_page_renders(self):
        """Students management page renders roster and face status"""
        self.login_client()
        response = self.client.get('/students')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Student Management', response.data)
        self.assertIn(b'21BCE001', response.data)
        self.assertIn(b'Face Biometric Status', response.data)

    def test_courses_page_renders(self):
        """Courses page renders course catalog and enrollment triggers"""
        self.login_client()
        response = self.client.get('/courses')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Course &amp; Enrollment Management', response.data)
        self.assertIn(b'Software Engineering Lab', response.data)

    def test_live_session_screen_renders(self):
        """Live session screen renders video viewport, scanner HUD and attendance table"""
        self.login_client()
        response = self.client.get('/sessions/101')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'LIVE ATTENDANCE SESSION', response.data)
        self.assertIn(b'sessionVideo', response.data)
        self.assertIn(b'recognitionStatusPill', response.data)
        self.assertIn(b'Duplicate Protection Active', response.data)

    def test_reports_page_renders(self):
        """Reports page renders student percentages table and CSV export button"""
        self.login_client()
        response = self.client.get('/reports')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Attendance Reports &amp; Analytics', response.data)
        self.assertIn(b'Export CSV Report', response.data)
        self.assertIn(b'Student Attendance Percentages', response.data)

    def test_face_registration_api(self):
        """Student face biometric registration endpoint updates student record"""
        payload = {'image': 'data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD...'}
        response = self.client.post('/api/students/1/register-face', json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data.get('status'), 'success')

    def test_course_enrollment_api(self):
        """Updating course roster updates enrolled IDs"""
        payload = {'student_ids': [1, 2, 3, 4]}
        response = self.client.post('/api/courses/1/enroll', json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data.get('status'), 'success')

    def test_duplicate_attendance_prevention_contract(self):
        """Marking manual attendance prevents duplicate entries in the same session"""
        # Mark student 6 for first time
        resp1 = self.client.post('/api/sessions/101/mark-manual', json={'student_id': 6})
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.get_json()
        self.assertEqual(data1.get('status'), 'marked')

        # Attempt to mark student 6 again in same session -> Must reject duplicate
        resp2 = self.client.post('/api/sessions/101/mark-manual', json={'student_id': 6})
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.get_json()
        self.assertEqual(data2.get('status'), 'already_marked')

    def test_csv_export_format(self):
        """CSV export endpoint returns text/csv with correct headers"""
        response = self.client.get('/api/reports/export-csv?course_id=CS301')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        csv_text = response.data.decode('utf-8')
        self.assertIn('Roll Number,Student Name,Email,Course Code', csv_text)
        self.assertIn('21BCE001,Aarav Sharma', csv_text)


if __name__ == '__main__':
    unittest.main()
