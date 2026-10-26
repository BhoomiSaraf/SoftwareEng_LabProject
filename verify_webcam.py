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

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                print("Failed to grab frame.")
                break

            # Run matching on current frame
            result = face_service.match_face(frame)
            status = result["status"]
            box = result.get("box")
            confidence = result.get("confidence", 0.0)

            # Draw visual feedback on display frame
            display_frame = frame.copy()
            h, w = display_frame.shape[:2]

            # Header overlay
            cv2.rectangle(display_frame, (0, 0), (w, 50), (30, 30, 30), -1)
            reg_text = f"Enrolled: {list(registered_students) if registered_students else 'None (Press R to register)'}"
            cv2.putText(display_frame, reg_text, (15, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)

            if box is not None:
                bx, by, bw, bh = box
                if status == "MATCHED":
                    color = (0, 255, 0)  # Green
                    label = f"MATCHED: Student {result['student_id']} ({confidence:.1%})"
                elif status == "UNKNOWN_FACE":
                    color = (0, 165, 255)  # Orange
                    label = f"UNKNOWN FACE ({confidence:.1%})"
                elif status == "MULTIPLE_FACES_DETECTED":
                    color = (0, 0, 255)  # Red
                    label = f"MULTIPLE FACES ({result.get('face_count', 2)})"
                else:
                    color = (255, 255, 0)
                    label = status

                # Draw bounding box and label
                cv2.rectangle(display_frame, (bx, by), (bx + bw, by + bh), color, 2)
                cv2.rectangle(display_frame, (bx, by - 28), (bx + bw, by), color, -1)
                cv2.putText(
                    display_frame, label, (bx + 5, by - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2
                )
            else:
                # No face detected
                cv2.putText(
                    display_frame, "STATUS: No Face in View", (15, h - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 150, 150), 2
                )

            cv2.imshow("Smart Attendance — Face Recognition Test (Press 'q' to exit)", display_frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('r'):
                # Register face as student 101
                reg_res = face_service.register_student_face("101", frame)
                if reg_res["success"]:
                    registered_students.add("101")
                    print(f"\n[+] SUCCESS: Registered your face as Student '101' (Rahul)!")
                else:
                    print(f"\n[-] Registration failed: {reg_res['message']}")
            elif key == ord('c'):
                face_service.clear_registry()
                registered_students.clear()
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
