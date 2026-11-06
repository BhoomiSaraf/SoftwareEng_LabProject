"""
seed_demo.py - Build a ready-to-demo database from seed/sample_data.json.

    python seed_demo.py                 # reset: back up the old DB/embeddings, rebuild from scratch
    python seed_demo.py --keep          # add anything missing to the existing DB (never deletes)
    python seed_demo.py --with-history  # also create past sessions for SAMPLE students (marked
                                        # 'Simulated Scanner') so reports have data to show

Students that have a "photo" in the JSON are real: their face is enrolled from that image.
All other students are sample data and have no face enrolled until an admin captures one.
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import json
import random
import shutil
import argparse
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

import database
from config import Config
from face_recognition_service import face_service

ROOT = os.path.dirname(os.path.abspath(__file__))
SEED_FILE = os.path.join(ROOT, 'seed', 'sample_data.json')
BACKUP_DIR = os.path.join(ROOT, 'backups')


def backup_existing(db_path, emb_path):
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    os.makedirs(BACKUP_DIR, exist_ok=True)
    for path in (db_path, emb_path):
        if path and os.path.exists(path):
            shutil.copy2(path, os.path.join(BACKUP_DIR, f"{stamp}-{os.path.basename(path)}"))
            os.remove(path)
            print(f"  backed up and removed {os.path.basename(path)}")


def seed(conn, data):
    domain = data['email_domain']
    default_pw = data['faculty_default_password']

    for a in data['admins']:
        if not conn.execute("SELECT 1 FROM users WHERE username = ?;", (a['username'],)).fetchone():
            conn.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin');",
                         (a['username'], generate_password_hash(a['password'])))

    for f in data['faculty']:
        if conn.execute("SELECT 1 FROM faculty WHERE faculty_id = ?;", (f['faculty_id'],)).fetchone():
            continue
        cur = conn.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'faculty');",
                           (f['username'], generate_password_hash(f.get('password', default_pw))))
        conn.execute(
            "INSERT INTO faculty (faculty_id, user_id, name, email, department) VALUES (?, ?, ?, ?, ?);",
            (f['faculty_id'], cur.lastrowid, f['name'], f"{f['username']}@{domain}", f['department'])
        )

    existing = {r[0] for r in conn.execute("SELECT student_id FROM students;")}
    n = len(existing)
    for st in data['students']:
        row = conn.execute("SELECT student_id FROM students WHERE roll_number = ?;", (st['roll_number'],)).fetchone()
        if row:
            st['student_id'] = row[0]
            continue
        n += 1
        st['student_id'] = f"STU{n:03d}"
        first = st['name'].split()[0].lower()
        email = st.get('email') or f"{first}.{st['roll_number']}@muj.manipal.edu"
        conn.execute(
            """INSERT INTO students (student_id, roll_number, name, email, program, semester, face_registered, section)
               VALUES (?, ?, ?, ?, 'B.Tech CSE', 5, 0, ?);""",
            (st['student_id'], st['roll_number'], st['name'], email, st['section'].upper())
        )

    for c in data['courses']:
        course_id = f"CRS-{c['code']}"
        sections = c['sections']
        lead = sections[sorted(sections)[0]]
        if not conn.execute("SELECT 1 FROM courses WHERE course_id = ?;", (course_id,)).fetchone():
            conn.execute(
                """INSERT INTO courses (course_id, course_code, course_name, credits, faculty_id, semester, academic_year)
                   VALUES (?, ?, ?, ?, ?, ?, ?);""",
                (course_id, c['code'], c['name'], c['credits'], lead, c['semester'], Config.DEFAULT_ACADEMIC_YEAR)
            )
        for sec, fac in sections.items():
            conn.execute(
                "INSERT OR REPLACE INTO course_sections (course_id, section, faculty_id) VALUES (?, ?, ?);",
                (course_id, sec.upper(), fac)
            )
            conn.execute(
                """INSERT OR IGNORE INTO enrollments (course_id, student_id)
                   SELECT ?, student_id FROM students WHERE UPPER(section) = ?;""",
                (course_id, sec.upper())
            )
    conn.commit()


def enroll_real_faces(conn, data, emb_path):
    """Enrol every student that ships with a reference photo."""
    if os.path.exists(emb_path):
        face_service.load_embeddings(emb_path)
    for st in data['students']:
        photo = st.get('photo')
        if not photo:
            continue
        path = photo if os.path.isabs(photo) else os.path.join(ROOT, photo)
        if not os.path.isfile(path):
            print(f"  ! photo missing for {st['name']}: {photo}")
            continue
        face_service.remove_student(st['student_id'])
        res = face_service.register_student_face(st['student_id'], path)
        print(f"  face for {st['name']} ({st['student_id']}): {res['status']}")
        if res.get('success'):
            conn.execute("UPDATE students SET face_registered = 1 WHERE student_id = ?;", (st['student_id'],))
    # re-enrol anyone whose reference photo was saved by the admin UI (data/faces/<student_id>.jpg)
    for (sid,) in conn.execute("SELECT student_id FROM students;").fetchall():
        path = os.path.join(ROOT, 'data', 'faces', f"{sid}.jpg")
        if os.path.isfile(path) and sid not in face_service.get_registered_student_ids():
            res = face_service.register_student_face(sid, path)
            print(f"  face for {sid} from saved photo: {res['status']}")
    face_service.save_embeddings(emb_path)
    # enrolment flag must mirror the embeddings usable by the current model
    enrolled = set(face_service.get_registered_student_ids())
    for (sid,) in conn.execute("SELECT student_id FROM students;").fetchall():
        conn.execute("UPDATE students SET face_registered = ? WHERE student_id = ?;", (1 if sid in enrolled else 0, sid))
    conn.commit()


def add_history(conn, data, sessions_per_section=5):
    """Past completed sessions with simulated attendance for sample (photo-less) students only."""
    rng = random.Random(2026)
    real = {s['student_id'] for s in data['students'] if s.get('photo')}
    today = datetime.now()
    for cs in conn.execute("SELECT course_id, section, faculty_id FROM course_sections;").fetchall():
        course_id, section, fac = cs
        roster = [r[0] for r in conn.execute(
            """SELECT s.student_id FROM enrollments e JOIN students s ON s.student_id = e.student_id
               WHERE e.course_id = ? AND UPPER(s.section) = ?;""", (course_id, section))]
        for i in range(sessions_per_section):
            when = today - timedelta(days=7 * (sessions_per_section - i))
            sid = f"SES-{course_id[4:]}-{section}-{when.strftime('%Y%m%d')}"
            conn.execute(
                """INSERT OR IGNORE INTO class_sessions
                   (session_id, course_id, faculty_id, date, start_time, end_time, status, topic, section)
                   VALUES (?, ?, ?, ?, '10:00:00', '10:50:00', 'Completed', ?, ?);""",
                (sid, course_id, fac, when.strftime('%Y-%m-%d'), f"Lecture {i + 1}", section)
            )
            for stu in roster:
                if stu in real:
                    continue
                # a stable per-student attendance habit, so a few students end up below 75%
                habit = random.Random(stu).uniform(0.55, 1.0)
                if rng.random() < habit:
                    conn.execute(
                        """INSERT OR IGNORE INTO attendance_records
                           (session_id, student_id, course_id, status, marking_method, verified_by)
                           VALUES (?, ?, ?, 'Present', 'Simulated Scanner', 'Seed data');""",
                        (sid, stu, course_id)
                    )
    conn.commit()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--keep', action='store_true', help='keep the existing DB and only add missing rows')
    ap.add_argument('--with-history', action='store_true', help='add simulated past sessions for sample students')
    args = ap.parse_args()

    db_path = Config.DB_PATH or database.DEFAULT_DB_PATH
    emb_path = Config.EMBEDDINGS_FILE
    data = json.load(open(SEED_FILE, encoding='utf-8'))

    print(f"Seeding {db_path}")
    if not args.keep:
        backup_existing(db_path, emb_path)
    database.init_db(db_path)

    conn = database.get_db_connection(db_path)
    seed(conn, data)
    enroll_real_faces(conn, data, emb_path)
    if args.with_history:
        add_history(conn, data)

    for label, table in [('users', 'users'), ('faculty', 'faculty'), ('courses', 'courses'),
                         ('students', 'students'), ('course sections', 'course_sections'),
                         ('enrolments', 'enrollments'), ('sessions', 'class_sessions')]:
        print(f"  {label:16}{conn.execute(f'SELECT COUNT(*) FROM {table};').fetchone()[0]}")
    conn.close()
    print("Done. Logins: admin / admin123, <faculty username> / faculty123 (e.g. rajesh.kumar)")


if __name__ == '__main__':
    main()
