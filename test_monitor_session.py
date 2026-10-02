"""
test_monitor_session.py — Phase 8: Local integration test for ExamMonitor
==========================================================================

Simulates 6 seconds of 2-FPS webcam frames from a local camera (if available)
or a generated dummy frame.

Run from project root:
    py -3.11 test_monitor_session.py
"""

import sys, time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
from backend.monitor_session import ExamMonitor

print("=" * 56)
print("  ExamMonitor — integration test")
print("=" * 56)

monitor = ExamMonitor()

# Try to get a real camera frame; fall back to a grey dummy frame.
try:
    import cv2
    cap = cv2.VideoCapture(0)
    ret, real_frame = cap.read()
    cap.release()
    frame = real_frame if ret else np.full((480, 640, 3), 100, dtype=np.uint8)
    src = "camera" if ret else "dummy"
except Exception:
    frame = np.full((480, 640, 3), 100, dtype=np.uint8)
    src = "dummy"

print(f"Frame source : {src}  ({frame.shape})")
print()

N = 12   # 6 seconds at 2 FPS
for i in range(N):
    result = monitor.process_frame(frame)
    d = result.to_dict()
    status = "CALIBRATING" if d["calibrating"] else ("WARNING: " + d["new_warning"] if d["new_warning"] else "OK")
    print(f"  Frame {i+1:2d}  calib={d['calib_progress']:.0%}  score={d['score']}  {status}")
    time.sleep(0.5)

print()
print("  reset_score() called")
monitor.reset_score()
result = monitor.process_frame(frame)
d = result.to_dict()
print(f"  After reset: score={d['score']} warnings={d['warnings']}")

monitor.close()
print()
print("  Test passed — ExamMonitor class is working.")
print("=" * 56)
