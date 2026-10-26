"""
Face Recognition Service Module
Part of the Smart Attendance System MVP (Manipal University Jaipur)

Responsibilities:
1. Open and read webcam frames using OpenCV safely.
2. Detect faces using OpenCV Haar Cascade Classifier.
3. Generate normalized embeddings using a lightweight pretrained model (MobileNetV3).
4. Match captured faces against registered embeddings using cosine similarity.
5. Return recognized student ID or an explicit unknown/no-face/multi-face status.
6. Handle missing cameras, no-face frames, multiple faces, and decode errors gracefully.
7. Expose a stable, documented interface for frontend and backend consumption.

Architectural Rule:
This module does NOT write to the attendance database or enforce attendance business rules.
It only performs face detection, registration, and recognition matching.
"""

import os
import re
import io
import base64
import logging
from typing import Union, Optional, Tuple, List, Dict, Any

import cv2
import numpy as np

# Configure logging
logger = logging.getLogger("FaceRecognitionService")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [FaceRecognitionService] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Optional PyTorch import with graceful fallback
TORCH_AVAILABLE = False
try:
    import torch
    import torch.nn as nn
    import torchvision.models as models
    import torchvision.transforms as transforms
    from PIL import Image
    TORCH_AVAILABLE = True
except ImportError:
    logger.warning("PyTorch/torchvision not found. Using lightweight feature extractor fallback.")


class FaceRecognitionService:
    """
    Core Face Recognition and Registration service.
    
    Attributes:
        similarity_threshold (float): Minimum cosine similarity required to declare a match.
        haar_cascade_path (str): Path to Haar Cascade XML file for face detection.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.70,
        haar_cascade_path: Optional[str] = None
    ):
        """
        Initialize the Face Recognition Service with models and face detectors.
        
        Args:
            similarity_threshold: Cosine similarity cutoff (default: 0.70).
            haar_cascade_path: Custom path to haarcascade_frontalface_default.xml.
        """
        self.similarity_threshold = float(similarity_threshold)
        
        # In-memory dictionary: student_id (str) -> List[np.ndarray (1D float32)]
        self._registered_embeddings: Dict[str, List[np.ndarray]] = {}

        # 1. Initialize Face Detector
        if haar_cascade_path and os.path.exists(haar_cascade_path):
            self.detector_path = haar_cascade_path
        else:
            self.detector_path = os.path.join(
                cv2.data.haarcascades, "haarcascade_frontalface_default.xml"
            )

        self.face_cascade = cv2.CascadeClassifier(self.detector_path)
        if self.face_cascade.empty():
            logger.error(f"Failed to load Haar Cascade from {self.detector_path}")
        else:
            logger.info("Face detector (Haar Cascade) loaded successfully.")

        # 2. Initialize Pretrained Embedding Extractor
        self.torch_model = None
        self.transform = None
        self._init_embedding_model()

    def _init_embedding_model(self) -> None:
        """Initialize the embedding extraction model (MobileNetV3 or fallback)."""
        global TORCH_AVAILABLE
        if TORCH_AVAILABLE:
            try:
                # Use MobileNetV3-Small (lightweight ~9MB, fast inference on CPU)
                weights = models.MobileNet_V3_Small_Weights.DEFAULT
                model = models.mobilenet_v3_small(weights=weights)
                # Replace classifier with Identity to extract pooled 576-d feature vector
                model.classifier = nn.Identity()
                model.eval()
                self.torch_model = model

                self.transform = transforms.Compose([
                    transforms.Resize((224, 224)),
                    transforms.ToTensor(),
                    transforms.Normalize(
                        mean=[0.485, 0.456, 0.406],
                        std=[0.229, 0.224, 0.225]
                    ),
                ])
                logger.info("Torch MobileNetV3 feature extractor initialized (dim=576).")
                return
            except Exception as e:
                logger.warning(f"Error loading PyTorch model: {e}. Falling back to visual feature extractor.")

        # Fallback if PyTorch unavailable or failed
        logger.info("Initialized OpenCV multi-scale spatial histogram feature extractor.")

    # -------------------------------------------------------------------------
    # Hardware & Camera Operations
    # -------------------------------------------------------------------------

    def check_webcam_availability(self, device_index: int = 0) -> Tuple[bool, str]:
        """
        Check if a webcam device is accessible without keeping the stream locked.
        
        Args:
            device_index: Hardware device index (default: 0).
            
        Returns:
            Tuple of (is_available: bool, status_message: str)
        """
        cap = cv2.VideoCapture(device_index)
        if not cap.isOpened():
            cap.release()
            return False, f"Webcam device {device_index} is unavailable or in use by another application."
        
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None or frame.size == 0:
            return False, f"Webcam device {device_index} opened but failed to capture a valid frame."
        
        h, w = frame.shape[:2]
        return True, f"Webcam device {device_index} is functional (resolution: {w}x{h})."

    def open_webcam(self, device_index: int = 0) -> Tuple[bool, Optional[cv2.VideoCapture], str]:
        """
        Open a continuous OpenCV video capture stream.
        
        Args:
            device_index: Hardware device index (default: 0).
            
        Returns:
            Tuple of (success: bool, VideoCapture object or None, status_message: str)
        """
        try:
            cap = cv2.VideoCapture(device_index)
            if not cap.isOpened():
                return False, None, f"Could not open webcam index {device_index}."
            return True, cap, f"Webcam index {device_index} opened successfully."
        except Exception as e:
            return False, None, f"Exception while opening webcam: {str(e)}"

    def read_webcam_frame(self, cap: cv2.VideoCapture) -> Tuple[bool, Optional[np.ndarray], str]:
        """
        Read a single frame from an active VideoCapture instance.
        
        Args:
            cap: An open cv2.VideoCapture instance.
            
        Returns:
            Tuple of (success: bool, frame (BGR np.ndarray) or None, status_message: str)
        """
        if cap is None or not cap.isOpened():
            return False, None, "VideoCapture instance is closed or uninitialized."
        
        ret, frame = cap.read()
        if not ret or frame is None or frame.size == 0:
            return False, None, "Failed to capture frame from webcam stream."
        
        return True, frame, "Frame captured successfully."

    def capture_single_frame(self, device_index: int = 0) -> Tuple[bool, Optional[np.ndarray], str]:
        """
        One-shot convenience function: opens camera, grabs a single frame, and closes it.
        
        Args:
            device_index: Hardware device index (default: 0).
            
        Returns:
            Tuple of (success: bool, frame (BGR np.ndarray) or None, status_message: str)
        """
        cap = cv2.VideoCapture(device_index)
        if not cap.isOpened():
            cap.release()
            return False, None, f"Camera index {device_index} unavailable."
        
        ret, frame = cap.read()
        cap.release()
        
        if not ret or frame is None or frame.size == 0:
            return False, None, "Failed to read frame from camera."
        
        return True, frame, "Frame captured successfully."

    # -------------------------------------------------------------------------
    # Image Input Decoding & Preprocessing
    # -------------------------------------------------------------------------

    def decode_image(self, input_data: Union[np.ndarray, bytes, str]) -> np.ndarray:
        """
        Normalize and decode various input formats into a standard BGR numpy array.
        
        Supported input formats:
        - np.ndarray: Raw BGR or RGB image.
        - bytes: Raw image file bytes (JPEG, PNG).
        - str: Base64 data URI ("data:image/jpeg;base64,..."), raw base64 string, or valid file path.
        
        Returns:
            Decoded BGR image as uint8 np.ndarray.
            
        Raises:
            ValueError: If input format is invalid, empty, or cannot be decoded.
        """
        if input_data is None:
            raise ValueError("Image input is None.")

        # 1. Already a numpy array
        if isinstance(input_data, np.ndarray):
            if input_data.size == 0:
                raise ValueError("Numpy array is empty.")
            if input_data.ndim == 2:
                # Grayscale to BGR
                return cv2.cvtColor(input_data, cv2.COLOR_GRAY2BGR)
            elif input_data.ndim == 3 and input_data.shape[2] in (3, 4):
                if input_data.shape[2] == 4:
                    return cv2.cvtColor(input_data, cv2.COLOR_BGRA2BGR)
                return input_data.copy()
            else:
                raise ValueError(f"Invalid image array shape: {input_data.shape}")

        # 2. Raw bytes
        if isinstance(input_data, bytes):
            nparr = np.frombuffer(input_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("Failed to decode image from byte buffer.")
            return img

        # 3. String (Base64 or Filepath)
        if isinstance(input_data, str):
            # Check if it's a file path
            if os.path.isfile(input_data):
                img = cv2.imread(input_data)
                if img is None:
                    raise ValueError(f"Could not read image from path: {input_data}")
                return img

            # Strip Base64 Data URI scheme if present (e.g. data:image/jpeg;base64,...)
            base64_str = re.sub(r"^data:image\/[a-zA-Z]+;base64,", "", input_data.strip())
            try:
                raw_bytes = base64.b64decode(base64_str)
                nparr = np.frombuffer(raw_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is None:
                    raise ValueError("Failed to decode image from base64 string.")
                return img
            except Exception as e:
                raise ValueError(f"Invalid base64 image data: {str(e)}")

        raise ValueError(f"Unsupported image input type: {type(input_data).__name__}")

    # -------------------------------------------------------------------------
    # Face Detection & Embedding Generation
    # -------------------------------------------------------------------------

    def detect_faces(
        self,
        image: np.ndarray,
        scale_factor: float = 1.1,
        min_neighbors: int = 5,
        min_size: Tuple[int, int] = (40, 40)
    ) -> List[Tuple[int, int, int, int]]:
        """
        Detect face bounding boxes in an image using Haar Cascade.
        
        Args:
            image: BGR numpy image.
            scale_factor: Parameter specifying how much the image size is reduced at each scale.
            min_neighbors: Parameter specifying how many neighbors each candidate rectangle should retain.
            min_size: Minimum possible face size in pixels.
            
        Returns:
            List of bounding boxes in (x, y, w, h) format.
        """
        if image is None or image.size == 0:
            return []

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Apply histogram equalization to enhance contrast in diverse lighting conditions
        gray = cv2.equalizeHist(gray)

        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=scale_factor,
            minNeighbors=min_neighbors,
            minSize=min_size,
            flags=cv2.CASCADE_SCALE_IMAGE
        )

        # Convert numpy array to list of tuples
        return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]

    def extract_embedding(self, face_crop: np.ndarray) -> np.ndarray:
        """
        Generate a normalized 1D feature vector for a cropped face region.
        
        Args:
            face_crop: BGR numpy image of the cropped face.
            
        Returns:
            1D numpy array of float32 with unit L2 norm (||v|| = 1.0).
        """
        if face_crop is None or face_crop.size == 0:
            raise ValueError("Face crop is empty or None.")

        # Primary: PyTorch MobileNetV3
        if self.torch_model is not None and self.transform is not None:
            try:
                rgb_crop = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb_crop)
                tensor = self.transform(pil_img).unsqueeze(0)

                with torch.no_grad():
                    raw_emb = self.torch_model(tensor).cpu().numpy().flatten().astype(np.float32)

                norm = np.linalg.norm(raw_emb)
                if norm > 1e-8:
                    return raw_emb / norm
                return raw_emb
            except Exception as e:
                logger.warning(f"Torch inference error: {e}. Falling back to spatial histogram.")

        # Fallback: Spatial Multi-Region Histogram & Gradient Descriptor (Normalized 512-d vector)
        resized = cv2.resize(face_crop, (64, 64))
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

        # Compute Sobel Gradients
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag, ang = cv2.cartToPolar(gx, gy, angleInDegrees=True)

        # Compute 4x4 spatial grid of 32-bin histograms
        hist_parts = []
        for r in range(4):
            for c in range(4):
                cell_gray = gray[r*16:(r+1)*16, c*16:(c+1)*16]
                h, _ = np.histogram(cell_gray, bins=32, range=(0, 256))
                hist_parts.append(h.astype(np.float32))

        vector = np.concatenate(hist_parts).astype(np.float32)
        norm = np.linalg.norm(vector)
        if norm > 1e-8:
            vector = vector / norm
        return vector

    # -------------------------------------------------------------------------
    # Registration & Matching Business Methods
    # -------------------------------------------------------------------------

    def register_student_face(
        self,
        student_id: Union[int, str],
        image_input: Union[np.ndarray, bytes, str],
        padding: float = 0.1
    ) -> Dict[str, Any]:
        """
        Detect a face from the provided registration image and store its embedding.
        
        Validation Rules:
        - Must contain exactly 1 face. If 0 or >1 faces, registration fails with explicit message.
        - Stores only normalized numeric embeddings (no raw biometric images saved).
        
        Args:
            student_id: Unique student identifier.
            image_input: Image in any supported format (bytes, numpy, base64, path).
            padding: Additional fractional margin to include around detected face box.
            
        Returns:
            Dict containing:
            - success (bool): True if registered.
            - status (str): 'REGISTERED', 'NO_FACE_DETECTED', 'MULTIPLE_FACES_DETECTED', or 'ERROR'.
            - student_id (str): String representation of student ID.
            - message (str): Human-readable descriptive status.
            - embedding_dim (int): Dimensionality of registered embedding.
        """
        student_key = str(student_id).strip()
        if not student_key:
            return {
                "success": False,
                "status": "ERROR",
                "student_id": None,
                "message": "Student ID cannot be empty."
            }

        try:
            image = self.decode_image(image_input)
        except Exception as e:
            return {
                "success": False,
                "status": "ERROR",
                "student_id": student_key,
                "message": f"Image decoding error: {str(e)}"
            }

        faces = self.detect_faces(image)

        if len(faces) == 0:
            return {
                "success": False,
                "status": "NO_FACE_DETECTED",
                "student_id": student_key,
                "message": "No face detected in the registration image. Ensure good lighting and facing the camera directly."
            }

        if len(faces) > 1:
            return {
                "success": False,
                "status": "MULTIPLE_FACES_DETECTED",
                "face_count": len(faces),
                "student_id": student_key,
                "message": f"{len(faces)} faces detected. Registration requires exactly one face in frame."
            }

        # Exactly 1 face found: crop with safe bounds
        x, y, w, h = faces[0]
        ih, iw = image.shape[:2]
        pad_x = int(w * padding)
        pad_y = int(h * padding)

        x1 = max(0, x - pad_x)
        y1 = max(0, y - pad_y)
        x2 = min(iw, x + w + pad_x)
        y2 = min(ih, y + h + pad_y)

        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            crop = image[y:y+h, x:x+w]

        embedding = self.extract_embedding(crop)

        # Store in registry
        if student_key not in self._registered_embeddings:
            self._registered_embeddings[student_key] = []
        self._registered_embeddings[student_key].append(embedding)

        logger.info(f"Student '{student_key}' face registered successfully (total samples: {len(self._registered_embeddings[student_key])}).")

        return {
            "success": True,
            "status": "REGISTERED",
            "student_id": student_key,
            "box": [x, y, w, h],
            "embedding_dim": int(embedding.shape[0]),
            "message": f"Face registered successfully for student {student_key}."
        }

    def match_face(
        self,
        image_input: Union[np.ndarray, bytes, str],
        allowed_student_ids: Optional[List[Union[int, str]]] = None,
        threshold: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Process a probe frame, detect face, and match against enrolled embeddings.
        
        Args:
            image_input: Input frame from webcam (bytes, numpy, base64, path).
            allowed_student_ids: Optional list of student IDs enrolled in the active course.
                                 If provided, only enrolled students are considered for matching.
            threshold: Optional override for matching cosine similarity threshold.
            
        Returns:
            Dict containing:
            - status (str): 'MATCHED', 'UNKNOWN_FACE', 'NO_FACE_DETECTED', 'MULTIPLE_FACES_DETECTED', or 'ERROR'.
            - student_id (str or None): Recognized student ID if matched, else None.
            - confidence (float): Best cosine similarity score (0.0 to 1.0).
            - box (list or None): Detected face box [x, y, w, h].
            - message (str): Human-readable outcome description.
        """
        match_threshold = float(threshold) if threshold is not None else self.similarity_threshold

        try:
            image = self.decode_image(image_input)
        except Exception as e:
            return {
                "status": "ERROR",
                "student_id": None,
                "confidence": 0.0,
                "box": None,
                "message": f"Failed to decode frame: {str(e)}"
            }

        faces = self.detect_faces(image)

        if len(faces) == 0:
            return {
                "status": "NO_FACE_DETECTED",
                "student_id": None,
                "confidence": 0.0,
                "box": None,
                "message": "No face detected in camera view."
            }

        if len(faces) > 1:
            boxes = [[int(x), int(y), int(w), int(h)] for (x, y, w, h) in faces]
            return {
                "status": "MULTIPLE_FACES_DETECTED",
                "face_count": len(faces),
                "student_id": None,
                "confidence": 0.0,
                "boxes": boxes,
                "box": boxes[0],
                "message": f"{len(faces)} faces detected. Please present one face at a time for attendance."
            }

        # Single face detected
        x, y, w, h = faces[0]
        crop = image[y:y+h, x:x+w]
        probe_embedding = self.extract_embedding(crop)

        # Determine target candidates
        if allowed_student_ids is not None:
            allowed_set = {str(sid).strip() for sid in allowed_student_ids}
            candidates = {k: v for k, v in self._registered_embeddings.items() if k in allowed_set}
        else:
            candidates = self._registered_embeddings

        if not candidates:
            return {
                "status": "UNKNOWN_FACE",
                "student_id": None,
                "confidence": 0.0,
                "box": [x, y, w, h],
                "message": "Face detected, but no enrolled student records are available to compare against."
            }

        best_student_id = None
        best_similarity = -1.0

        for sid, emb_list in candidates.items():
            for enrolled_emb in emb_list:
                # Cosine similarity for unit vectors: dot product
                sim = float(np.dot(probe_embedding, enrolled_emb))
                if sim > best_similarity:
                    best_similarity = sim
                    best_student_id = sid

        best_confidence = max(0.0, min(1.0, (best_similarity + 1.0) / 2.0 if best_similarity < 0 else best_similarity))

        if best_student_id is not None and best_similarity >= match_threshold:
            return {
                "status": "MATCHED",
                "student_id": str(best_student_id),
                "confidence": round(float(best_similarity), 4),
                "box": [x, y, w, h],
                "message": f"Student '{best_student_id}' recognized with confidence {best_similarity:.2%}."
            }
        else:
            return {
                "status": "UNKNOWN_FACE",
                "student_id": None,
                "confidence": round(float(best_similarity), 4),
                "box": [x, y, w, h],
                "message": f"Unrecognized face (highest confidence {best_similarity:.2%} is below threshold {match_threshold:.2%})."
            }

    # -------------------------------------------------------------------------
    # Persistence & Management of Numeric Embeddings
    # -------------------------------------------------------------------------

    def save_embeddings(self, filepath: str) -> bool:
        """
        Save the registered numeric embeddings dictionary to disk (npz format).
        
        Does NOT save any photos or raw biometric images. Only stores numerical arrays.
        
        Args:
            filepath: Destination file path (e.g. 'data/embeddings.npz').
            
        Returns:
            bool indicating success.
        """
        try:
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            # Store as dictionary of arrays: key -> (N, D) array
            export_dict = {}
            for sid, emb_list in self._registered_embeddings.items():
                export_dict[f"student_{sid}"] = np.vstack(emb_list).astype(np.float32)
            
            np.savez_compressed(filepath, **export_dict)
            logger.info(f"Saved {len(export_dict)} student embeddings to {filepath}.")
            return True
        except Exception as e:
            logger.error(f"Failed to save embeddings to {filepath}: {e}")
            return False

    def load_embeddings(self, filepath: str) -> bool:
        """
        Load registered numeric embeddings from an npz file on disk.
        
        Args:
            filepath: Path to saved npz file.
            
        Returns:
            bool indicating success.
        """
        if not os.path.exists(filepath):
            logger.warning(f"Embeddings file does not exist: {filepath}")
            return False

        try:
            data = np.load(filepath)
            count = 0
            for key in data.files:
                if key.startswith("student_"):
                    sid = key[len("student_"):]
                    matrix = data[key]
                    self._registered_embeddings[sid] = [matrix[i] for i in range(matrix.shape[0])]
                    count += 1
            logger.info(f"Loaded {count} student embeddings from {filepath}.")
            return True
        except Exception as e:
            logger.error(f"Failed to load embeddings from {filepath}: {e}")
            return False

    def get_registered_student_ids(self) -> List[str]:
        """Return list of all registered student IDs."""
        return list(self._registered_embeddings.keys())

    def clear_registry(self) -> None:
        """Clear in-memory registered embeddings."""
        self._registered_embeddings.clear()
        logger.info("Face recognition registry cleared.")


# Global singleton instance for easy import and sharing across routes
face_service = FaceRecognitionService()
