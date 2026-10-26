"""
Unit and Integration Tests for FaceRecognitionService
Part of the Smart Attendance System MVP (Manipal University Jaipur)

Validates all 7 assigned responsibilities:
1. Webcam opening and reading / missing camera handling.
2. Image input decoding (numpy, bytes, base64 data URI).
3. Face detection handling (no face, multiple faces, single face).
4. Embedding extraction (576-dim normalized vector, unit L2 norm).
5. Student face registration flow.
6. Face matching against registered embeddings with configurable threshold.
7. Explicit status reporting: MATCHED, UNKNOWN_FACE, NO_FACE_DETECTED, MULTIPLE_FACES_DETECTED.
8. Serialization and persistence of embeddings (no raw biometric images saved).
"""

import os
import tempfile
import base64
import unittest
import numpy as np
import cv2

from face_recognition_service import FaceRecognitionService


class TestFaceRecognitionService(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Initialize service instance once for all tests."""
        cls.service = FaceRecognitionService(similarity_threshold=0.70)

    def setUp(self):
        """Clear registered embeddings before each test."""
        self.service.clear_registry()

    # -------------------------------------------------------------------------
    # 1. Camera & Hardware Tests
    # -------------------------------------------------------------------------

    def test_missing_camera_handling(self):
        """Verify graceful error reporting when an invalid camera index is requested."""
        is_avail, msg = self.service.check_webcam_availability(device_index=999)
        self.assertFalse(is_avail)
        self.assertIn("unavailable", msg.lower())

        success, cap, open_msg = self.service.open_webcam(device_index=999)
        self.assertFalse(success)
        self.assertIsNone(cap)

    def test_read_from_uninitialized_camera(self):
        """Verify safe handling when reading from None or closed capture."""
        success, frame, msg = self.service.read_webcam_frame(None)
        self.assertFalse(success)
        self.assertIsNone(frame)
        self.assertIn("uninitialized", msg.lower())

    # -------------------------------------------------------------------------
    # 2. Input Decoding Tests
    # -------------------------------------------------------------------------

    def test_decode_numpy_array(self):
        """Verify decoding standard BGR numpy image."""
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        decoded = self.service.decode_image(img)
        self.assertEqual(decoded.shape, (100, 100, 3))

    def test_decode_grayscale_numpy_array(self):
        """Verify converting grayscale array to 3-channel BGR."""
        img = np.zeros((100, 100), dtype=np.uint8)
        decoded = self.service.decode_image(img)
        self.assertEqual(decoded.shape, (100, 100, 3))

    def test_decode_encoded_bytes(self):
        """Verify decoding raw JPEG byte stream."""
        img = np.ones((80, 80, 3), dtype=np.uint8) * 128
        _, buf = cv2.imencode(".jpg", img)
        decoded = self.service.decode_image(buf.tobytes())
        self.assertEqual(decoded.shape, (80, 80, 3))

    def test_decode_base64_data_uri(self):
        """Verify decoding standard web canvas data URI string."""
        img = np.ones((60, 60, 3), dtype=np.uint8) * 200
        _, buf = cv2.imencode(".jpg", img)
        b64_str = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("utf-8")
        decoded = self.service.decode_image(b64_str)
        self.assertEqual(decoded.shape, (60, 60, 3))

    def test_decode_invalid_input(self):
        """Verify ValueError is raised on corrupt or None image input."""
        with self.assertRaises(ValueError):
            self.service.decode_image(None)

        with self.assertRaises(ValueError):
            self.service.decode_image(b"not-an-image-data")

    # -------------------------------------------------------------------------
    # 3. Embedding Extraction Tests
    # -------------------------------------------------------------------------

    def test_extract_embedding_properties(self):
        """Verify embedding dimensionality and unit L2 normalization."""
        synthetic_crop = np.random.randint(0, 255, (112, 112, 3), dtype=np.uint8)
        embedding = self.service.extract_embedding(synthetic_crop)

        self.assertIsInstance(embedding, np.ndarray)
        self.assertEqual(embedding.ndim, 1)
        self.assertIn(embedding.shape[0], (576, 512))  # MobileNetV3 or fallback
        # Verify L2 norm is ~1.0
        norm = np.linalg.norm(embedding)
        self.assertAlmostEqual(norm, 1.0, places=4)

    def test_extract_embedding_empty_crop(self):
        """Verify error handling on empty crop."""
        with self.assertRaises(ValueError):
            self.service.extract_embedding(np.empty((0, 0, 3), dtype=np.uint8))

    # -------------------------------------------------------------------------
    # 4. Face Detection & Validation States
    # -------------------------------------------------------------------------

    def test_no_face_detected_in_blank_image(self):
        """Verify that a blank solid image triggers NO_FACE_DETECTED."""
        blank_img = np.zeros((300, 300, 3), dtype=np.uint8)
        
        reg_result = self.service.register_student_face("101", blank_img)
        self.assertFalse(reg_result["success"])
        self.assertEqual(reg_result["status"], "NO_FACE_DETECTED")
        self.assertIn("No face detected", reg_result["message"])

        match_result = self.service.match_face(blank_img)
        self.assertEqual(match_result["status"], "NO_FACE_DETECTED")
        self.assertIsNone(match_result["student_id"])
        self.assertEqual(match_result["confidence"], 0.0)

    def test_multiple_faces_detected_handling(self):
        """Verify that multiple detected faces return MULTIPLE_FACES_DETECTED."""
        # Mock detect_faces to simulate 2 detected faces
        original_detect = self.service.detect_faces
        try:
            self.service.detect_faces = lambda img: [(20, 20, 50, 50), (120, 20, 50, 50)]
            dummy_img = np.zeros((200, 200, 3), dtype=np.uint8)

            reg_result = self.service.register_student_face("102", dummy_img)
            self.assertFalse(reg_result["success"])
            self.assertEqual(reg_result["status"], "MULTIPLE_FACES_DETECTED")
            self.assertEqual(reg_result["face_count"], 2)

            match_result = self.service.match_face(dummy_img)
            self.assertEqual(match_result["status"], "MULTIPLE_FACES_DETECTED")
            self.assertEqual(match_result["face_count"], 2)
            self.assertIsNone(match_result["student_id"])
        finally:
            self.service.detect_faces = original_detect

    # -------------------------------------------------------------------------
    # 5. Face Registration & Matching End-to-End Flow
    # -------------------------------------------------------------------------

    def test_registration_and_exact_match(self):
        """Verify successful registration and positive match for the registered face."""
        original_detect = self.service.detect_faces
        try:
            # Mock single face detection box
            self.service.detect_faces = lambda img: [(10, 10, 80, 80)]
            test_frame = np.ones((200, 200, 3), dtype=np.uint8) * 150
            # Add unique texture to ensure stable embedding
            cv2.circle(test_frame, (50, 50), 30, (30, 40, 50), -1)

            # Register student 101
            reg_res = self.service.register_student_face("101", test_frame)
            self.assertTrue(reg_res["success"])
            self.assertEqual(reg_res["status"], "REGISTERED")
            self.assertEqual(reg_res["student_id"], "101")
            self.assertIn("101", self.service.get_registered_student_ids())

            # Match with the identical frame
            match_res = self.service.match_face(test_frame, threshold=0.70)
            self.assertEqual(match_res["status"], "MATCHED")
            self.assertEqual(match_res["student_id"], "101")
            self.assertGreaterEqual(match_res["confidence"], 0.70)
            self.assertIsNotNone(match_res["box"])
        finally:
            self.service.detect_faces = original_detect

    def test_unknown_face_rejection_below_threshold(self):
        """Verify that an unregistered/different face is classified as UNKNOWN_FACE."""
        original_detect = self.service.detect_faces
        try:
            self.service.detect_faces = lambda img: [(10, 10, 80, 80)]

            # Register student 101 with pattern A
            img_a = np.zeros((200, 200, 3), dtype=np.uint8)
            cv2.rectangle(img_a, (10, 10), (90, 90), (255, 255, 255), -1)
            self.service.register_student_face("101", img_a)

            # Match probe with completely different pattern B (and high threshold)
            img_b = np.zeros((200, 200, 3), dtype=np.uint8)
            cv2.circle(img_b, (50, 50), 40, (100, 150, 200), -1)

            # Test with strict threshold
            match_res = self.service.match_face(img_b, threshold=0.99)
            self.assertEqual(match_res["status"], "UNKNOWN_FACE")
            self.assertIsNone(match_res["student_id"])
        finally:
            self.service.detect_faces = original_detect

    def test_match_with_course_filtering(self):
        """Verify that allowed_student_ids restricts matching to enrolled students."""
        original_detect = self.service.detect_faces
        try:
            self.service.detect_faces = lambda img: [(10, 10, 80, 80)]

            img_a = np.ones((200, 200, 3), dtype=np.uint8) * 100
            # Register student 101
            self.service.register_student_face("101", img_a)

            # Match probe with student 101, but course only allows student [102, 103]
            match_res = self.service.match_face(img_a, allowed_student_ids=["102", "103"])
            self.assertEqual(match_res["status"], "UNKNOWN_FACE")
            self.assertIsNone(match_res["student_id"])
            self.assertIn("no enrolled student records", match_res["message"].lower())

            # Now allow student 101 in course
            match_res_allowed = self.service.match_face(img_a, allowed_student_ids=["101", "102"])
            self.assertEqual(match_res_allowed["status"], "MATCHED")
            self.assertEqual(match_res_allowed["student_id"], "101")
        finally:
            self.service.detect_faces = original_detect

    # -------------------------------------------------------------------------
    # 6. Serialization & Persistence Tests
    # -------------------------------------------------------------------------

    def test_save_and_load_embeddings(self):
        """Verify saving numeric embeddings to disk and reloading into a fresh instance."""
        # Manually register two synthetic vectors
        dummy_v1 = np.ones(576, dtype=np.float32) / np.sqrt(576)
        dummy_v2 = np.zeros(576, dtype=np.float32)
        dummy_v2[0] = 1.0

        self.service._registered_embeddings["101"] = [dummy_v1]
        self.service._registered_embeddings["102"] = [dummy_v2]

        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = os.path.join(tmpdir, "test_embeddings.npz")
            
            # Save
            success = self.service.save_embeddings(save_path)
            self.assertTrue(success)
            self.assertTrue(os.path.exists(save_path))

            # New instance
            fresh_service = FaceRecognitionService()
            fresh_service.clear_registry()
            self.assertEqual(len(fresh_service.get_registered_student_ids()), 0)

            # Load
            load_success = fresh_service.load_embeddings(save_path)
            self.assertTrue(load_success)
            self.assertCountEqual(fresh_service.get_registered_student_ids(), ["101", "102"])
            
            # Verify loaded vectors are equal
            np.testing.assert_allclose(
                fresh_service._registered_embeddings["101"][0], dummy_v1, rtol=1e-5
            )


if __name__ == "__main__":
    unittest.main()
