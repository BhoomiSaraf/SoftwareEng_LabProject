"""
Interactive Face Recognition Verification Script
Part of the Smart Attendance System MVP (Manipal University Jaipur)

Run this script to test the face recognition module with your live webcam:
    python verify_webcam.py

Controls in the webcam window:
    'r' - Register your face as Student "101" (Rahul)
    'c' - Clear registered faces
    'q' - Quit verification
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import sys
import cv2
from face_recognition_service import face_service


def run_verification():
    print("=" * 60)
    print(" Smart Attendance System — Face Recognition Verification")
    print("=" * 60)

    # 1. Check hardware availability
    print("\n[Step 1] Checking webcam availability...")
    is_avail, msg = face_service.check_webcam_availability(device_index=0)
    print(f" -> {msg}")

    if not is_avail:
        print("\n[!] No active webcam detected on device 0.")
        print("    Running headless synthetic verification instead...")
        run_headless_verification()
        return

    # 2. Open live webcam
    print("\n[Step 2] Opening live webcam stream...")
    success, cap, open_msg = face_service.open_webcam(device_index=0)
    if not success or cap is None:
        print(f" -> Error: {open_msg}")
        return

    print("\n" + "=" * 60)
    print(" CONTROLS:")
    print("   Press 'r' : Register currently visible face as Student 101 (Rahul)")
    print("   Press 'c' : Clear registered student faces")
    print("   Press 'q' : Quit verification")
    print("=" * 60 + "\n")

    registered_students = set()
    smoothed_box = None
    smoothed_conf = 0.0
    active_status = "NO_FACE_DETECTED"
    active_result = {}
    lost_frames = 0
    MAX_LOST_FRAMES = 5  # Hold box for up to 5 dropped frames to eliminate flickering

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                print("Failed to grab frame.")
                break

            # Mirror the frame horizontally for natural selfie view
            frame = cv2.flip(frame, 1)

            # Run matching on the current frame
            raw_result = face_service.match_face(frame)
            raw_status = raw_result["status"]
            raw_box = raw_result.get("box")
            raw_conf = raw_result.get("confidence", 0.0)

            # Temporal smoothing logic
            if raw_box is not None:
                lost_frames = 0
                active_status = raw_status
                active_result = raw_result
                bx, by, bw, bh = [float(v) for v in raw_box]

                if smoothed_box is None:
                    smoothed_box = [bx, by, bw, bh]
                    smoothed_conf = raw_conf
                else:
                    # Exponential Moving Average (alpha=0.35) for rock-solid stability
                    alpha = 0.35
                    smoothed_box[0] = alpha * bx + (1 - alpha) * smoothed_box[0]
                    smoothed_box[1] = alpha * by + (1 - alpha) * smoothed_box[1]
                    smoothed_box[2] = alpha * bw + (1 - alpha) * smoothed_box[2]
                    smoothed_box[3] = alpha * bh + (1 - alpha) * smoothed_box[3]
                    smoothed_conf = alpha * raw_conf + (1 - alpha) * smoothed_conf
            else:
                # No face detected in raw frame: check persistence grace period
                if smoothed_box is not None and lost_frames < MAX_LOST_FRAMES:
                    lost_frames += 1
                else:
                    smoothed_box = None
                    active_status = "NO_FACE_DETECTED"
                    active_result = {}
                    smoothed_conf = 0.0

            # Draw visual feedback
            display_frame = frame.copy()
            h, w = display_frame.shape[:2]

            # Header overlay
            cv2.rectangle(display_frame, (0, 0), (w, 52), (24, 24, 24), -1)
            reg_text = f"Enrolled: {list(registered_students) if registered_students else 'None (Press R to enroll current face)'}"
            cv2.putText(display_frame, reg_text, (15, 33), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 220, 220), 2)

            if smoothed_box is not None:
                sbx, sby, sbw, sbh = [int(round(v)) for v in smoothed_box]

                if active_status == "MATCHED":
                    color = (0, 230, 80)  # Bright Green
                    label = f"MATCHED: Student {active_result.get('student_id')} ({smoothed_conf:.1%})"
                elif active_status == "UNKNOWN_FACE":
                    color = (0, 160, 255)  # Orange
                    label = f"UNKNOWN FACE ({smoothed_conf:.1%})"
                elif active_status == "MULTIPLE_FACES_DETECTED":
                    color = (0, 0, 255)  # Red
                    label = f"MULTIPLE FACES ({active_result.get('face_count', 2)})"
                else:
                    color = (255, 200, 0)
                    label = active_status

                # Draw smooth bounding box with rounded corners / thick frame
                cv2.rectangle(display_frame, (sbx, sby), (sbx + sbw, sby + sbh), color, 2)
                # Text badge background
                badge_w = max(180, len(label) * 11)
                cv2.rectangle(display_frame, (sbx, sby - 28), (sbx + badge_w, sby), color, -1)
                cv2.putText(
                    display_frame, label, (sbx + 6, sby - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 2
                )
            else:
                # No face detected
                cv2.putText(
                    display_frame, "STATUS: Looking for face...", (15, h - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (130, 130, 130), 2
                )

            # Footer instructions
            cv2.putText(
                display_frame, "[R] Register Face   [C] Clear   [Q] Quit", (15, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1
            )

            cv2.imshow("Smart Attendance — Face Recognition Test (Press 'q' to exit)", display_frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('r'):
                # Register currently visible face as student 101
                reg_res = face_service.register_student_face("101", frame)
                if reg_res["success"]:
                    registered_students.add("101")
                    print(f"\n[+] SUCCESS: Registered your face as Student '101' (Rahul)!")
                else:
                    print(f"\n[-] Registration failed: {reg_res['message']}")
            elif key == ord('c'):
                face_service.clear_registry()
                registered_students.clear()
                smoothed_box = None
                print("\n[*] Cleared all registered faces.")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("\nVerification closed.")


def run_headless_verification():
    """Fallback synthetic verification if no display window or camera is available."""
    import numpy as np

    print("\nRunning synthetic test pipeline...")
    # Test blank image
    blank = np.zeros((200, 200, 3), dtype=np.uint8)
    res_blank = face_service.match_face(blank)
    print(f" -> Blank image test: status='{res_blank['status']}' (Expected: NO_FACE_DETECTED)")

    # Test single face registration & matching
    face_service.detect_faces = lambda img: [(10, 10, 80, 80)]
    test_face = np.ones((100, 100, 3), dtype=np.uint8) * 150
    cv2.circle(test_face, (50, 50), 25, (10, 20, 30), -1)

    reg = face_service.register_student_face("101", test_face)
    print(f" -> Registration test: success={reg['success']}, student_id='{reg.get('student_id')}'")

    match = face_service.match_face(test_face)
    print(f" -> Matching test: status='{match['status']}', student_id='{match.get('student_id')}', confidence={match.get('confidence'):.2%}")
    print("\n[OK] Pipeline verified successfully!")


if __name__ == "__main__":
    run_verification()
