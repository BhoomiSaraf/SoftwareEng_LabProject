"""
enroll_faces.py - Enrol students from photo files and check they can be told apart.

    1. Put one clear, front-facing photo per student in  data/faces/inbox/
       named after the student, e.g.  karan_choudhary.jpg, rohan_mehta.png
       (a roll number or student id such as STU006 also works).
    2. python enroll_faces.py

Each photo is matched to a student by name / roll number / student id, enrolled with the SFace pipeline,
copied to data/faces/<student_id>.jpg, and the students table is updated. Afterwards the script prints, for every
enrolled student, the best look-alike so you can spot pairs that may need better photos.
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import re
import shutil
import sys

import cv2
import numpy as np

import database
from config import Config
from face_recognition_service import face_service

ROOT = os.path.dirname(os.path.abspath(__file__))
INBOX = os.path.join(ROOT, 'data', 'faces', 'inbox')
FACES = os.path.join(ROOT, 'data', 'faces')


def slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', text.lower())


def main():
    os.makedirs(INBOX, exist_ok=True)
    files = [f for f in sorted(os.listdir(INBOX)) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    if not files:
        print(f"No photos found in {INBOX}")
        return 1

    emb_path = Config.EMBEDDINGS_FILE
    if os.path.exists(emb_path):
        face_service.load_embeddings(emb_path)
    conn = database.get_db_connection(Config.DB_PATH or database.DEFAULT_DB_PATH)
    students = conn.execute("SELECT student_id, roll_number, name, section FROM students;").fetchall()

    for fname in files:
        key = slug(os.path.splitext(fname)[0])
        hits = [s for s in students if key in (slug(s['name']), slug(s['roll_number']), slug(s['student_id']))]
        if len(hits) != 1:
            print(f"  skip {fname}: {'no student' if not hits else 'several students'} matches '{key}'")
            continue
        st = hits[0]
        src = os.path.join(INBOX, fname)
        face_service.remove_student(st['student_id'])
        res = face_service.register_student_face(st['student_id'], src)
        print(f"  {st['name']:20} ({st['student_id']}, sec {st['section']}): {res['status']}"
              + ('' if res.get('success') else f" - {res.get('message')}"))
        if res.get('success'):
            cv2.imwrite(os.path.join(FACES, f"{st['student_id']}.jpg"), cv2.imread(src))

    face_service.save_embeddings(emb_path)
    enrolled = set(face_service.get_registered_student_ids())
    for s in students:
        conn.execute("UPDATE students SET face_registered = ? WHERE student_id = ?;",
                     (1 if s['student_id'] in enrolled else 0, s['student_id']))
    conn.commit()

    # look-alike report
    names = {s['student_id']: s['name'] for s in students}
    ids = [i for i in face_service.get_registered_student_ids() if i in names]
    print("\nClosest look-alike per enrolled student (cosine; matching threshold is "
          f"{face_service.similarity_threshold:.2f}):")
    for a in ids:
        best = max((b for b in ids if b != a),
                   key=lambda b: max(float(x @ y) for x in face_service._registered_embeddings[a]
                                     for y in face_service._registered_embeddings[b]), default=None)
        if best:
            sim = max(float(x @ y) for x in face_service._registered_embeddings[a] for y in face_service._registered_embeddings[best])
            flag = "  <-- close, use a clearer photo" if sim >= face_service.similarity_threshold else ""
            print(f"  {names[a]:20} ~ {names[best]:20} {sim:.2f}{flag}")
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
