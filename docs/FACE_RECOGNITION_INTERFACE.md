# Face Recognition Module Interface Specification

**Project:** Smart Attendance System using Face-Recognition Scanner  
**Module:** [`face_recognition_service.py`](file:///c:/Users/hp/Documents/SoftwareEng_LabProject/face_recognition_service.py)  
**Assigned Owner:** Face Recognition Workstream  
**Target Consumer:** Backend Developer (`app.py`, `services/attendance_service.py`) and Frontend Scanner UI  

---

## 1. Overview and Architecture Boundary

This module is responsible **exclusively** for:
- Reading live webcam frames via OpenCV.
- Detecting faces using OpenCV Haar Cascades (`haarcascade_frontalface_default.xml`).
- Generating normalized 576-dimensional feature embeddings using a pretrained lightweight vision backbone (MobileNetV3).
- Matching probe face embeddings against enrolled student embeddings using cosine similarity.
- Detecting edge conditions: missing camera, no face detected, multiple faces in frame, unrecognized faces.

### Boundary Constraints:
- **No Direct Database Writes:** This module does **not** write to SQLite. It only returns match results.
- **No Attendance Business Rules:** Session validation, course enrollment checks, and duplicate-prevention are handled by the attendance service.
- **Privacy First:** Raw biometric images are **never** persisted to disk or committed to Git. Only anonymized, normalized float32 arrays are saved.
- **No Unsubstantiated Claims:** Liveness / anti-spoofing is not implemented and must not be claimed.

---

## 2. Public API Function Signatures

Import the singleton instance or instantiate `FaceRecognitionService`:

```python
from face_recognition_service import face_service, FaceRecognitionService
```

### A. Match Face Frame (Main Attendance Scanner Call)
Used during an active attendance session when the camera captures a frame.

```python
def match_face(
    image_input: Union[np.ndarray, bytes, str],
    allowed_student_ids: Optional[List[Union[int, str]]] = None,
    threshold: Optional[float] = None
) -> Dict[str, Any]
```

- **`image_input`**: Accepts:
  - `np.ndarray`: OpenCV BGR/RGB frame.
  - `bytes`: Raw JPEG/PNG image bytes.
  - `str`: Base64 data URI (e.g., `data:image/jpeg;base64,...`), raw base64 string, or local file path.
- **`allowed_student_ids`** *(optional)*: List of enrolled student IDs for the active class session (e.g. `["101", "102", "103"]`). If provided, matching is restricted only to this subset.
- **`threshold`** *(optional)*: Cosine similarity cutoff (defaults to `0.70`).

#### Return Schema:
```json
// Successful Match:
{
  "status": "MATCHED",
  "student_id": "101",
  "confidence": 0.8421,
  "box": [120, 80, 180, 180],
  "message": "Student '101' recognized with confidence 84.21%."
}

// Unrecognized / Low Confidence Face:
{
  "status": "UNKNOWN_FACE",
  "student_id": null,
  "confidence": 0.5120,
  "box": [120, 80, 180, 180],
  "message": "Unrecognized face (highest confidence 51.20% is below threshold 70.00%)."
}

// No Face in Frame:
{
  "status": "NO_FACE_DETECTED",
  "student_id": null,
  "confidence": 0.0,
  "box": null,
  "message": "No face detected in camera view."
}

// Multiple Faces:
{
  "status": "MULTIPLE_FACES_DETECTED",
  "face_count": 2,
  "student_id": null,
  "confidence": 0.0,
  "boxes": [[50, 40, 100, 100], [220, 40, 110, 110]],
  "box": [50, 40, 100, 100],
  "message": "2 faces detected. Please present one face at a time for attendance."
}

// Decoding / Hardware Error:
{
  "status": "ERROR",
  "student_id": null,
  "confidence": 0.0,
  "box": null,
  "message": "Failed to decode frame: Invalid base64 string."
}
```

---

### B. Register Student Face
Used when an administrator or faculty registers a student's face template.

```python
def register_student_face(
    student_id: Union[int, str],
    image_input: Union[np.ndarray, bytes, str],
    padding: float = 0.1
) -> Dict[str, Any]
```

- **Validation:** Ensures exactly **1 face** is detected. Fails with `NO_FACE_DETECTED` or `MULTIPLE_FACES_DETECTED` if invalid.
- **Storage:** Computes and appends the normalized 576-d vector under key `str(student_id)`.

#### Return Schema:
```json
{
  "success": true,
  "status": "REGISTERED",
  "student_id": "101",
  "box": [100, 90, 150, 150],
  "embedding_dim": 576,
  "message": "Face registered successfully for student 101."
}
```

---

### C. Webcam Controls & Hardware Checks

```python
# Check if camera index 0 is available without holding the lock:
is_available, status_msg = face_service.check_webcam_availability(device_index=0)

# Capture a single frame (opens camera, reads 1 frame, and closes):
success, frame_bgr, msg = face_service.capture_single_frame(device_index=0)

# Continuous stream management:
success, cap, msg = face_service.open_webcam(device_index=0)
success, frame_bgr, msg = face_service.read_webcam_frame(cap)
cap.release()
```

---

### D. Embeddings Persistence

```python
# Save registered embeddings to disk (compressed numpy arrays, zero raw images)
face_service.save_embeddings("data/embeddings.npz")

# Load registered embeddings at application startup
face_service.load_embeddings("data/embeddings.npz")
```

---

## 3. Integration Examples for Backend & Frontend

### Flask Route Example (`app.py`):
```python
from flask import Flask, request, jsonify
from face_recognition_service import face_service
# from services.attendance_service import attendance_service

@app.route("/api/attendance/scan-frame", methods=["POST"])
def scan_frame():
    data = request.get_json() or {}
    frame_b64 = data.get("frame")
    session_id = data.get("session_id")
    course_enrolled_students = ["101", "102", "103"] # from session/course DB

    # 1. Run face recognition
    result = face_service.match_face(
        image_input=frame_b64,
        allowed_student_ids=course_enrolled_students,
        threshold=0.70
    )

    if result["status"] != "MATCHED":
        return jsonify({
            "success": False,
            "recognition_status": result["status"],
            "message": result["message"],
            "box": result.get("box")
        }), 200

    student_id = result["student_id"]
    confidence = result["confidence"]

    # 2. Hand off to attendance service (validates duplicate, active session, writes DB)
    # is_marked, msg, record = attendance_service.mark_attendance(
    #     session_id=session_id, student_id=student_id, method="FACE_SCAN"
    # )

    return jsonify({
        "success": True,
        "recognition_status": "MATCHED",
        "student_id": student_id,
        "confidence": confidence,
        "box": result.get("box"),
        "message": f"Recognized student {student_id}."
    })
```

### Frontend Video Stream & Capture (`scanner.js`):
```javascript
// Capture current video frame from HTML5 <video id="webcam">
function captureFrame() {
  const video = document.getElementById("webcam");
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.85); // Returns data:image/jpeg;base64,...
}

// POST frame to backend
async function sendFrameForRecognition(sessionId) {
  const frameData = captureFrame();
  const response = await fetch("/api/attendance/scan-frame", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, frame: frameData })
  });
  const data = await response.json();
  console.log("Recognition result:", data);
}
```

---

## 4. Verification & Running Unit Tests

Execute the automated test suite with Python:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

All 15 test cases cover camera fallbacks, input decoders, face detection edge cases, MobileNetV3 embedding extraction, registration, matching, course filtering, and `.npz` persistence.
