"""
Test configuration.

Most tests drive the HTTP/API plumbing with synthetic frames and monkeypatched detectors, so they run
against the legacy extractor. Real-photo recognition is covered separately in test_face_sface.py,
which builds its own SFace service instance.
"""
import os
import sys

os.environ.setdefault("FACE_BACKEND", "legacy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
