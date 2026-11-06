# Beta-Test Analysis and Makeover

Scope: this is a lab prototype. Nothing here aims at production hardening (no HTTPS setup, no migrations
framework, no liveness detection, no audit trail). Everything below was found by reading the code against the
project report and your beta-test notes, then fixed and covered by tests where practical.

## 1. Why "nothing worked"

| # | Finding | Effect in the beta test | Fix |
|---|---------|-------------------------|-----|
| 1 | `session.html` printed the session id into JavaScript **unquoted** (`sessionId: SES-CSE3132-2026...`). | The script block threw `ReferenceError`, `SESSION_CONFIG` was never set, and every scan went to `/api/sessions/undefined/recognize`. The live scanner was dead for every session. | Values are emitted with `\|tojson`. Regression test `test_live_session_page_config_is_valid_javascript`. |
| 2 | The "face model" was ImageNet MobileNetV3 (an object classifier) plus a Haar cascade. | Cosine similarity between *any* two faces is high, so with a 0.65 threshold nearly anyone matched the closest enrolled student. | YuNet detector + landmark alignment + SFace (trained for face verification), 128-d, threshold 0.45, plus an ambiguity margin. Old 576-d embeddings are detected and dropped. |
| 3 | Recognition compared the face with **every** enrolled student, then checked the roster afterwards. | A student from another course/section could "win" the match and the real student was never considered. The report asks for templates "relevant to the selected course". | Matching is limited to the session roster (course + section). If nothing on the roster matches, a second pass only produces a helpful message ("wrong section / not enrolled") and never marks attendance. |
| 4 | `face_registered` flags in the DB said "enrolled" for students that had no embedding, and numeric aliases (`"4"`, `21BCE004`, `STU001`...) were saved as separate embeddings. | Students looked enrolled but never matched; the same person existed under several keys. | Status comes from the embedding registry only. One key per student: the canonical `student_id`. No aliases, no positional numeric ids. |
| 5 | Courses were addressed by *list position* in the UI (`course.id` = row number) and students by a number parsed out of `STU004`. | Roster/enrol/report links silently pointed at the wrong record after any insert or reorder. | `id` is the real `course_id` / `student_id` everywhere (templates, JS, API). |
| 6 | Reports counted every session in a course against every student, and showed 100% when no session had been held. | Section-restricted sessions made students of other sections look absent; empty courses looked perfect. | Percentages use only sessions the student could attend (own section + whole-course). No sessions yet shows N/A. |
| 7 | The dashboard and course list showed everything to every teacher; "Start session" offered courses the teacher could not teach. | Starting a session often failed with "not authorised". | Teachers see only their own course sections; the launcher is course -> section limited to their assignments. |
| 8 | `reports?session_id=` links from the dashboard were ignored; the course filter on the Reports page only hid rows and left the totals stale; CSV export was not scoped to the teacher. | Dashboard "Report" button showed unrelated data; any teacher could export all courses. | Server-side course/section filters, a per-session present/absent report, CSV scoped by role and section. |
| 9 | Dev leftovers: "MVP" badge, prefilled demo credentials on the login form, `Dr. Alan Turing` fallback name, a hard-coded `enroll_bhoomi.py` / `populate_db.py` with fake roll numbers. | Looked unfinished; a second, conflicting data set. | Removed. One seed file drives the demo data. |
| 10 | `tests/test_frontend.py` ran against the live `smart_attendance.db` using hard-coded ids (`101`, `CS301`, `21BCE001`). | Tests passed or failed depending on whatever data your beta test left behind. | Rewritten on an isolated temp DB built from the same seed file. |

## 2. Your feedback, item by item

| Request | Done |
|---------|------|
| Remove the MVP block | Badge removed from the navbar; no page contains "MVP" (test). |
| "Create new course" for admin only | Button hidden for faculty; route returns 403 for faculty. |
| "3rd pic should also be for admin" | I read this as the **roster/enrolment editor and face capture**. Both are admin-only now (UI hidden, APIs return 403). Teachers get a read-only roster of their own sections. If you meant a different screen, tell me which. |
| "Register new student" admin only | Button and modal hidden for faculty; route returns 403. |
| Divide students course-wise and section-wise | New `course_sections` table (course x section -> teacher). Students carry a section; sessions, rosters, recognition, reports and CSV are all section-aware. Registering a student auto-enrols them in their section's courses. |
| Let teachers choose course and section | Start-session dialog: course -> section, restricted to the teacher's assignments, with roster size shown. |
| Add more teachers and courses | 8 teachers, 10 courses (core + electives + labs), 27 course-section assignments, in `seed/sample_data.json`. |
| Keep your photo/record real, hard-code other students | Bhoomi Saraf (`STU001`, roll `229301045`) is enrolled from `data/faces/bhoomi_saraf.jpg`. 27 sample students have no face until an admin captures one. Nothing is hard-coded in application code; it all lives in the JSON. |

## 3. Behavioural changes to know about

* Sessions are for **one section**. Admins do not start sessions (they manage; teachers conduct).
* Starting a new session for a section closes that section's previous live session only (other sections are untouched).
* Admin-only actions return a plain 403 for faculty instead of a flash message.
* `RECOGNITION_THRESHOLD` now defaults to the model's own value (0.45 for SFace); set the env var to override.
* `torch` is no longer required. It is only used by the legacy fallback, which the synthetic-frame tests still exercise.

## 4. Deliberately left out (prototype scope)

Liveness / anti-spoofing (excluded by the report), audit trail for manual corrections, low-attendance e-mail alerts
(the 75% flag is shown in reports and CSV), student login, Absent records written at session close (absent = on the roster
with no record), password reset, teacher/admin CRUD screens for faculty accounts (done through the seed file),
`BACKEND_CONTRACT.md` and `docs/FACE_RECOGNITION_INTERFACE.md` still describe the old numeric-id contract.

## 5. How to verify

```powershell
python fetch_models.py ; python seed_demo.py ; python run_frontend_dev.py
```
1. Sign in as `rajesh.kumar` / `faculty123`, Start Session -> CSE3132 -> Section A, switch on the camera: Bhoomi is marked.
2. Sign in as `meenakshi.s`, start CSE3132 Section B and scan the same face: "Wrong Section", nothing is recorded.
3. Sign in as `admin`: create a course, reassign a section teacher, edit a roster, capture a face for another student.

Automated: `python -m pytest -q` (91 tests; the 6 real-photo SFace tests skip if the models or photo are missing).
