"""
fetch_models.py - Download the OpenCV Zoo ONNX models used for face detection and recognition.

    python fetch_models.py

YuNet (detector, ~0.2 MB) and SFace (recognizer, ~37 MB) are saved to ./models_cv/.
They are not committed to git; run this once after cloning.
"""

import os
import shutil
import subprocess
import urllib.request

BASE = "https://github.com/opencv/opencv_zoo/raw/main/models"
MODELS = {
    "yunet.onnx": f"{BASE}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "sface.onnx": f"{BASE}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}
TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models_cv")


def main():
    os.makedirs(TARGET, exist_ok=True)
    for name, url in MODELS.items():
        dest = os.path.join(TARGET, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 100_000:
            print(f"ok       {name} already present")
            continue
        print(f"fetching {name} ...")
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as err:       # e.g. SSL trust-store problems on some Windows setups
            curl = shutil.which("curl")
            if not curl:
                raise SystemExit(f"download failed ({err}); fetch {url} manually into {TARGET}")
            subprocess.run([curl, "-fsSL", "-o", dest, url], check=True)
        print(f"saved    {dest} ({os.path.getsize(dest) // 1024} KB)")


if __name__ == "__main__":
    main()
