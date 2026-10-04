# models/

MediaPipe model files used by `src/mediapipe_processor.py`. They are **not committed to Git**;
download them once with:

```bash
py -3.11 setup_models.py
```

This creates `face_landmarker.task`, `hand_landmarker.task` and `pose_landmarker.task` here.
The YOLOv8n weights (`yolov8n.pt`) are downloaded automatically by Ultralytics on first run
into the folder the backend is started from.
