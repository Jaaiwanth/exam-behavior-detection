# src — Exam Behavior Detection Source Code

This package contains the processing pipeline, organised by phase:

| File                      | Phase | Description                                    |
|---------------------------|-------|------------------------------------------------|
| `video_reader.py`         | 1     | OpenCV video ingestion and metadata collection |
| `mediapipe_processor.py`  | 2     | MediaPipe landmark extraction                  |
| `feature_extractor.py`    | 3     | Landmark → numerical feature engineering       |
| `temporal_features.py`    | 4     | Sliding window sequence generation             |
| `build_dataset.py`        | 4     | End-to-end dataset build pipeline              |
| `visualize_landmarks.py`  | 2     | Debugging / visualisation utilities            |
| `train_lstm.py`           | 5     | LSTM model definition and training             |

Each file is implemented and tested incrementally — see `implementation.md` for the current phase.
