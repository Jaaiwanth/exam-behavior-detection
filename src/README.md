# src — ML detectors used by the backend

`backend/monitor_session.py` combines these three detectors into the real-time exam monitor.

| File | Purpose |
|------|---------|
| `mediapipe_processor.py` | MediaPipe face / hand / pose landmarks and head pose per frame |
| `face_verifier.py` | Face identity check (dlib embeddings) to detect a different person |
| `object_detector.py` | YOLOv8n detection of phones, laptops, extra people and books |

Model files: MediaPipe `.task` files are downloaded into `models/` by `setup_models.py`;
`yolov8n.pt` is downloaded automatically by Ultralytics on first use.
