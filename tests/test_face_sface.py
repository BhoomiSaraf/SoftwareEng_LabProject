"""
Real-photo checks of the YuNet + SFace pipeline. Skipped when the ONNX models (python fetch_models.py)
or the reference photo are not present on this machine.
"""
import os

import cv2
import numpy as np
import pytest

from face_recognition_service import FaceRecognitionService

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOTO = os.path.join(ROOT, 'data', 'faces', 'bhoomi_saraf.jpg')
MODELS = os.path.join(ROOT, 'models_cv')

pytestmark = pytest.mark.skipif(
    not (os.path.exists(PHOTO) and os.path.exists(os.path.join(MODELS, 'sface.onnx'))),
    reason='SFace models or reference photo not available',
)


@pytest.fixture
def svc():
    s = FaceRecognitionService(backend='sface')
    assert s.backend == 'sface'
    return s


def webcam_like(img):
    """Different size, dimmer and slightly blurred, as a laptop webcam frame would be."""
    small = cv2.resize(img, None, fx=0.55, fy=0.55)
    dim = cv2.convertScaleAbs(small, alpha=0.78, beta=-12)
    return cv2.GaussianBlur(dim, (3, 3), 0)


def test_enrolled_face_is_recognised_in_a_degraded_frame(svc):
    img = cv2.imread(PHOTO)
    assert svc.register_student_face('STU001', img)['success']
    res = svc.match_face(webcam_like(img), allowed_student_ids=['STU001'])
    assert res['status'] == 'MATCHED' and res['student_id'] == 'STU001'
    assert res['confidence'] > svc.similarity_threshold


def test_embedding_is_unit_norm_128d(svc):
    img = cv2.imread(PHOTO)
    svc.register_student_face('STU001', img)
    emb = svc._registered_embeddings['STU001'][0]
    assert emb.shape == (128,) and abs(float(np.linalg.norm(emb)) - 1.0) < 1e-4


def test_blank_and_noise_frames_never_match(svc):
    img = cv2.imread(PHOTO)
    svc.register_student_face('STU001', img)
    blank = np.full((480, 640, 3), 127, np.uint8)
    noise = np.random.default_rng(1).integers(0, 255, (480, 640, 3), dtype=np.uint8)
    assert svc.match_face(blank)['status'] == 'NO_FACE_DETECTED'
    assert svc.match_face(noise)['status'] in ('NO_FACE_DETECTED', 'UNKNOWN_FACE')


def test_match_is_restricted_to_the_allowed_roster(svc):
    img = cv2.imread(PHOTO)
    svc.register_student_face('STU001', img)
    res = svc.match_face(webcam_like(img), allowed_student_ids=['STU999'])
    assert res['status'] == 'UNKNOWN_FACE'          # enrolled, but not on this roster


def test_two_faces_in_one_frame_are_rejected(svc):
    img = cv2.imread(PHOTO)
    h, w = img.shape[:2]
    canvas = np.hstack([img, img])
    res = svc.match_face(canvas)
    assert res['status'] == 'MULTIPLE_FACES_DETECTED' and canvas.shape[1] == 2 * w and h > 0


def test_stale_embeddings_from_another_backend_are_dropped(svc, tmp_path):
    path = str(tmp_path / 'old.npz')
    np.savez_compressed(path, student_OLD=np.ones((1, 576), np.float32), student_NEW=np.ones((1, 128), np.float32))
    assert svc.load_embeddings(path)
    assert svc.get_registered_student_ids() == ['NEW']
