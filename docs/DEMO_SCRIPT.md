# Project demo script (about 4 minutes, 3 speakers)

Before recording: server running (`python run_frontend_dev.py`), database seeded, browser logged out, webcam allowed.
Use two browser profiles or log out between roles. Bhoomi is in section A, Apoorva in section B.

## Speaker 1 - Bhoomi (0:00 - 1:20) Problem, design, admin side

**[Screen: title slide or login page]**
"Hello, we are Bhoomi Saraf, Kanakpreet Kaur and Apoorva Kala, and this is our CSE3132 project: the Smart Attendance System using a face-recognition scanner. Manual roll-call wastes lecture time and allows proxy attendance. Our system marks attendance automatically from a webcam, for the exact class section being taught."

**[Screen: architecture diagram from the report, 10 seconds]**
"It is a Flask web application with a SQLite database. Frames from the browser go to a face pipeline built on OpenCV YuNet for detection and SFace for recognition. Business rules live in an attendance service."

**[Screen: log in as admin / admin123, Admin Console]**
"There are two roles. I am logging in as the administrator, who owns the master data. Students belong to sections A, B or C."
**[Courses page -> Teachers button]**
"Each course is split by section, and the administrator chooses a teacher for every section. For example CSE3132 section A is taught by Dr. Rajesh Kumar and section B by Dr. Meenakshi Sharma."
**[Students page -> Capture Face]**
"Faces are enrolled here by the administrator only. The camera takes five frames, a quality check runs, and the embedding is stored. Faculty cannot see these controls."
"Over to Kanakpreet for the live session."

## Speaker 2 - Kanakpreet (1:20 - 2:50) Live attendance

**[Screen: log out, log in as rajesh.kumar / faculty123, dashboard]**
"Now I am a teacher. The dashboard shows only my courses and sections, 20 students, and my teaching load."
**[Start Attendance Session -> CSE3132 -> Section A]**
"I choose a course and then one of my sections. A teacher cannot pick a section they do not teach. The roster is exactly the students of that section."
**[Session page -> Start Camera -> Auto-Scan; Bhoomi in front of camera]**
"Frames are sent every one and a half seconds. The server finds the face, checks the image quality, matches it only against this roster, and needs two consistent scans before marking. Here Bhoomi is verified, her name appears in the log with the time and confidence, and the counters update."
**[Scan again]**
"Scanning her again is rejected as a duplicate, so one student can only have one record per session."
**[Show a message: move closer / wrong person if possible]**
"If the face is too far, dark or blurry the screen tells us what to fix instead of guessing. Unknown faces are never marked."
**[Manual Override accordion]**
"For edge cases, the teacher can mark a roster student manually."
"Over to Apoorva for the section check, reports and testing."

## Speaker 3 - Apoorva (2:50 - 4:00) Sections, reports, testing

**[Screen: log in as meenakshi.s, start CSE3132 Section B, scan Bhoomi]**
"This is the section rule. Dr. Meenakshi teaches section B. When Bhoomi, who is in section A, appears, the system answers Wrong Section and records nothing. I, Apoorva, am in section B, so I am marked here."
**[Close Session -> Reports page, open the session report]**
"Closing the session archives it. The report lists who was present and absent, and the course report shows each student's attendance percentage using only the sessions that apply to their section. Below 75 percent is flagged, and everything exports to CSV, scoped to what the teacher is allowed to see."
**[Screen: pytest output or Section 9 table of the report]**
"For testing we wrote 94 automated tests covering unit, integration, end-to-end, negative and security cases. All 94 pass. We also measured recognition: 40 of 40 genuine scans were correct, speed is about 63 milliseconds per frame, and the one weakness we found is look-alike pairs, which the system handles by rejecting ambiguous scans. The full SRS, UML diagrams, estimation, test cases and results are in our report."
"Thank you."
