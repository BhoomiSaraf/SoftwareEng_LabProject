"""
enroll_bhoomi.py - Biometric Face Enrollment & Verification Tool for Bhoomi Saraf
Smart Attendance System - Manipal University Jaipur (CSE3132)

Usage:
  1. Interactive Webcam Enrollment (Recommended):
     python enroll_bhoomi.py

  2. Direct Image File Enrollment:
     python enroll_bhoomi.py --image path/to/bhoomi_photo.jpg

  3. Live Recognition Test:
     python enroll_bhoomi.py --verify

  4. Check Current Biometric Status:
     python enroll_bhoomi.py --status
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import sys
import argparse
import time
import cv2
import numpy as np

from face_recognition_service import face_service

EMBEDDINGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
EMBEDDINGS_FILE = os.path.join(EMBEDDINGS_DIR, 'embeddings.npz')

STUDENT_NAME = "Bhoomi Saraf"
STUDENT_ID = "4"
STUDENT_ROLL = "21BCE004"
STUDENT_ALIASES = ["4", "21BCE004", "STU001", "229301045", "Bhoomi Saraf"]


def show_status():
    """Print the current biometric registration status for Bhoomi Saraf."""
    print("=" * 65)
    print(" Smart Attendance System — Biometric Registration Status")
    print("=" * 65)
    print(f" Target Student  : {STUDENT_NAME} (Roll: {STUDENT_ROLL})")
    print(f" Embeddings File : {EMBEDDINGS_FILE}")

    if not os.path.exists(EMBEDDINGS_FILE):
        print(" Status          : [NOT ENROLLED] Embeddings file does not exist yet.")
        print("\n Run 'python enroll_bhoomi.py' to enroll using your webcam.")
        return False

    loaded = face_service.load_embeddings(EMBEDDINGS_FILE)
    reg_ids = face_service.get_registered_student_ids()

    is_enrolled = any(alias in reg_ids for alias in STUDENT_ALIASES)
    if is_enrolled:
        samples = len(face_service._registered_embeddings.get(STUDENT_ID, []))
        print(f" Status          : [ENROLLED] Biometrics active ({samples} sample(s) registered).")
        print(" Registered Keys :", reg_ids)
        print("\n -> You can run 'python enroll_bhoomi.py --verify' to test live webcam recognition.")
        return True
    else:
        print(" Status          : [NOT ENROLLED] Bhoomi Saraf not found in embeddings file.")
        print(" Registered Keys :", reg_ids)
        return False


def enroll_from_image(image_path: str):
    """Enroll Bhoomi Saraf from an existing image file on disk."""
    print("=" * 65)
    print(" Biometric Face Enrollment from Image File")
    print("=" * 65)
    print(f" Candidate : {STUDENT_NAME} ({STUDENT_ROLL})")
    print(f" Image     : {image_path}")

    if not os.path.isfile(image_path):
        print(f"\n[ERROR] File not found: {image_path}")
        return False

    # Load existing embeddings first to prevent overwriting
    if os.path.exists(EMBEDDINGS_FILE):
        face_service.load_embeddings(EMBEDDINGS_FILE)

    res = face_service.register_student_face(STUDENT_ID, image_path)
    if not res.get("success"):
        print(f"\n[REGISTRATION FAILED] {res.get('message')}")
        return False

    # Register aliases so all lookup paths match
    for alias in STUDENT_ALIASES:
        face_service.register_student_face(alias, image_path)

    # Save to disk
    face_service.save_embeddings(EMBEDDINGS_FILE)
    print(f"\n[SUCCESS] {res.get('message')}")
    print(f" Feature Vector Dimension : {res.get('embedding_dim', 576)}")
    print(f" Saved To                 : {EMBEDDINGS_FILE}")
    print("\n -> Bhoomi Saraf is now fully enrolled! You can start the demo now.")
    return True


def enroll_from_webcam():
    """Interactive webcam enrollment interface for Bhoomi Saraf."""
    print("=" * 65)
    print(" Interactive Biometric Face Enrollment — Bhoomi Saraf")
    print("=" * 65)
    print(" Instructions:")
    print("   1. Center your face in the webcam window.")
    print("   2. When a GREEN box appears, press [SPACE] or [C] to capture.")
    print("   3. Press [Q] to exit without saving.")
    print("=" * 65)

    # Load existing embeddings first
    if os.path.exists(EMBEDDINGS_FILE):
        face_service.load_embeddings(EMBEDDINGS_FILE)

    success, cap, msg = face_service.open_webcam(0)
    if not success or cap is None:
        print(f"\n[ERROR] Could not access webcam: {msg}")
        return False

    window_name = "Smart Attendance - Enroll Bhoomi Saraf"
    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)

    captured = False
    registered_successfully = False

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            # Mirror frame for intuitive selfie view
            display_frame = cv2.flip(frame, 1)
            raw_frame_for_biometrics = display_frame.copy()

            # Detect faces in current frame
            faces = face_service.detect_faces(display_frame)

            h, w = display_frame.shape[:2]

            # Header overlay banner
            cv2.rectangle(display_frame, (0, 0), (w, 50), (20, 24, 33), -1)
            cv2.putText(
                display_frame,
                "ENROLL FACE: BHOOMI SARAF (21BCE004)",
                (15, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                2,
                cv2.LINE_AA
            )

            # Footer overlay banner
            cv2.rectangle(display_frame, (0, h - 45), (w, h), (20, 24, 33), -1)

            if len(faces) == 1:
                x, y, fw, fh = faces[0]
                # Draw high-tech green corner brackets / bounding box
                cv2.rectangle(display_frame, (x, y), (x + fw, y + fh), (0, 220, 100), 2)
                cv2.putText(
                    display_frame,
                    "Face Detected - Press [SPACE] to Register",
                    (15, h - 16),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 220, 100),
                    2,
                    cv2.LINE_AA
                )
            elif len(faces) > 1:
                cv2.putText(
                    display_frame,
                    f"Warning: {len(faces)} faces detected. Present one face.",
                    (15, h - 16),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 165, 255),
                    2,
                    cv2.LINE_AA
                )
            else:
                cv2.putText(
                    display_frame,
                    "No face detected. Center face with good lighting.",
                    (15, h - 16),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (180, 180, 180),
                    1,
                    cv2.LINE_AA
                )

            cv2.imshow(window_name, display_frame)
            key = cv2.waitKey(20) & 0xFF

            if key == ord('q') or key == 27:
                print("\n[INFO] Enrollment cancelled by user.")
                break
            elif key in (32, ord('c'), ord('C'), 13):  # SPACE, C, or ENTER
                if len(faces) == 0:
                    print("No face detected in frame. Please align your face inside the camera view.")
                    continue
                elif len(faces) > 1:
                    print(f"Multiple faces ({len(faces)}) detected. Please ensure only Bhoomi Saraf is in frame.")
                    continue

                print("\nCapturing face biometric embedding...")
                res = face_service.register_student_face(STUDENT_ID, raw_frame_for_biometrics)
                if res.get("success"):
                    for alias in STUDENT_ALIASES:
                        face_service.register_student_face(alias, raw_frame_for_biometrics)
                    face_service.save_embeddings(EMBEDDINGS_FILE)

                    # Show confirmation frame
                    cv2.rectangle(display_frame, (x, y), (x + fw, y + fh), (0, 255, 0), 4)
                    cv2.putText(
                        display_frame,
                        "REGISTERED SUCCESSFULLY!",
                        (x, max(30, y - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 0),
                        2,
                        cv2.LINE_AA
                    )
                    cv2.imshow(window_name, display_frame)
                    cv2.waitKey(1200)

                    registered_successfully = True
                    print(f"\n[SUCCESS] Biometric face enrolled for Bhoomi Saraf ({STUDENT_ROLL})!")
                    print(f" Feature Vector: 576-dimensional MobileNetV3 normalized embedding")
                    print(f" Saved To      : {EMBEDDINGS_FILE}")
                    break
                else:
                    print(f"[FAILED] {res.get('message')}")

    finally:
        cap.release()
        cv2.destroyAllWindows()

    return registered_successfully


def verify_webcam_live():
    """Live verification test to prove real-time facial recognition works."""
    print("=" * 65)
    print(" Live Webcam Verification — Testing Biometrics for Bhoomi Saraf")
    print("=" * 65)
    print(" Controls: Press [Q] to quit.")

    if not os.path.exists(EMBEDDINGS_FILE):
        print(f"\n[ERROR] No embeddings found at {EMBEDDINGS_FILE}.")
        print(" Run 'python enroll_bhoomi.py' first to enroll your face.")
        return

    face_service.load_embeddings(EMBEDDINGS_FILE)
    print(" Registered IDs in memory:", face_service.get_registered_student_ids())

    success, cap, msg = face_service.open_webcam(0)
    if not success or cap is None:
        print(f"\n[ERROR] Could not open webcam: {msg}")
        return

    window_name = "Live Verification - Smart Attendance System"
    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]

            # Run actual recognition
            result = face_service.match_face(frame, threshold=0.65)
            status = result.get("status")
            box = result.get("box")
            conf = result.get("confidence", 0.0)

            # Header
            cv2.rectangle(frame, (0, 0), (w, 50), (20, 24, 33), -1)
            cv2.putText(
                frame,
                "LIVE ATTENDANCE SCANNER - REAL BIOMETRICS",
                (15, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA
            )

            # Footer
            cv2.rectangle(frame, (0, h - 45), (w, h), (20, 24, 33), -1)

            if status == "MATCHED":
                matched_id = result.get("student_id")
                label = f"VERIFIED: Bhoomi Saraf ({conf:.1%})"
                color = (0, 220, 100)  # Green

                if box:
                    bx, by, bw, bh = box
                    cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), color, 3)
                    cv2.putText(
                        frame,
                        label,
                        (bx, max(30, by - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        color,
                        2,
                        cv2.LINE_AA
                    )

                cv2.putText(
                    frame,
                    f"Present Marked: Bhoomi Saraf (21BCE004) | Score: {conf:.2%}",
                    (15, h - 16),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    color,
                    2,
                    cv2.LINE_AA
                )

            elif status == "UNKNOWN_FACE":
                color = (0, 0, 255)  # Red
                if box:
                    bx, by, bw, bh = box
                    cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), color, 2)
                    cv2.putText(
                        frame,
                        f"Unrecognized Face ({conf:.1%})",
                        (bx, max(30, by - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        color,
                        2,
                        cv2.LINE_AA
                    )
                cv2.putText(
                    frame,
                    f"Face not recognized (Similarity {conf:.1%} < Threshold 65%)",
                    (15, h - 16),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    color,
                    2,
                    cv2.LINE_AA
                )

            elif status == "NO_FACE_DETECTED":
                cv2.putText(
                    frame,
                    "Searching for face in camera view...",
                    (15, h - 16),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (180, 180, 180),
                    1,
                    cv2.LINE_AA
                )

            elif status == "MULTIPLE_FACES_DETECTED":
                cv2.putText(
                    frame,
                    "Multiple faces detected. Please present one face at a time.",
                    (15, h - 16),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 165, 255),
                    2,
                    cv2.LINE_AA
                )

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(20) & 0xFF
            if key == ord('q') or key == 27:
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()


def clear_enrollment():
    """Clear registered embeddings."""
    if os.path.exists(EMBEDDINGS_FILE):
        os.remove(EMBEDDINGS_FILE)
    face_service.clear_registry()
    print("[INFO] Registered biometric embeddings cleared successfully.")


def main():
    parser = argparse.ArgumentParser(description="Biometric Enrollment Tool for Bhoomi Saraf")
    parser.add_argument("--image", type=str, help="Path to image file for enrollment")
    parser.add_argument("--verify", action="store_true", help="Launch live webcam verification preview")
    parser.add_argument("--status", action="store_true", help="Check current biometric enrollment status")
    parser.add_argument("--clear", action="store_true", help="Clear enrolled embeddings")

    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.clear:
        clear_enrollment()
    elif args.image:
        enroll_from_image(args.image)
    elif args.verify:
        verify_webcam_live()
    else:
        # Default: interactive webcam enrollment
        enroll_from_webcam()


if __name__ == "__main__":
    main()
