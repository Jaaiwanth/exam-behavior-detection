# Exam Behavior Detection

An AI-based exam monitoring system that recognises **observable student behaviours** from short webcam videos using computer vision and deep learning.

> **Disclaimer:** This system is a research prototype. It identifies observable behaviours for human review — it does **not** automatically classify anyone as "cheating".

---

## Project Goal

Build an end-to-end pipeline that:

1. Reads short exam-monitoring videos.
2. Extracts MediaPipe face, hand, and pose landmarks.
3. Engineers meaningful temporal features.
4. Trains an LSTM model to classify observable behaviours.
5. Feeds predictions into an evidence engine that flags suspicious patterns for a human reviewer.

---

## Observable Behaviours

| Category   | Behaviour            |
|------------|----------------------|
| Normal     | looking\_at\_screen  |
| Normal     | looking\_down        |
| Movement   | eye\_rubbing         |
| Movement   | adjusting\_glasses   |
| Movement   | drinking\_water      |
| Movement   | scratching\_face     |
| Movement   | yawning              |
| Suspicious | looking\_behind      |
| Suspicious | prolonged\_away      |
| Suspicious | repeated\_left       |
| Suspicious | repeated\_right      |

---

## System Architecture

```
Video
  ↓
OpenCV (video_reader.py)
  ↓
MediaPipe — Face + Hands + Pose (mediapipe_processor.py)
  ↓
Feature extraction (feature_extractor.py)
  ↓
Temporal sequences (temporal_features.py)
  ↓
LSTM behaviour classifier (train_lstm.py)
  ↓
Observable behaviour label
  ↓
Evidence / suspicious-activity engine
  ↓
Optional YOLO object detection
  ↓
Monitoring dashboard
```

---

## Project Structure

```
student_behavior/
│
├── dataset/
│   ├── README.md               ← dataset instructions
│   └── movements/
│       ├── adjusting_glasses/
│       ├── drinking_water/
│       ├── eye_rubbing/
│       ├── scratching_face/
│       ├── yawning/
│       ├── normal/
│       │   ├── looking_at_screen/
│       │   └── looking_down/
│       └── suspicious/
│           ├── looking_behind/
│           ├── prolonged_away/
│           ├── repeated_left/
│           └── repeated_right/
│
├── src/
│   ├── video_reader.py         ← Phase 1
│   ├── mediapipe_processor.py  ← Phase 2
│   ├── feature_extractor.py    ← Phase 3
│   ├── temporal_features.py    ← Phase 4
│   ├── build_dataset.py        ← Phase 4
│   ├── visualize_landmarks.py  ← Phase 2
│   └── train_lstm.py           ← Phase 5
│
├── outputs/
│   ├── frame_features/
│   ├── sequences/
│   └── visualizations/
│
├── models/
│
├── collect_data.py             ← webcam data collection utility
├── README.md
├── implementation.md
├── requirements.txt
└── .gitignore
```

---

## Development Phases

| Phase | Description                          | Status      |
|-------|--------------------------------------|-------------|
| 0     | Project setup                        | ✅ Complete |
| 1     | Video ingestion (OpenCV)             | ⬜ Pending  |
| 2     | MediaPipe landmark extraction        | ⬜ Pending  |
| 3     | Feature engineering                  | ⬜ Pending  |
| 4     | Temporal sequence generation         | ⬜ Pending  |
| 5     | LSTM baseline                        | ⬜ Pending  |
| 6     | Model evaluation                     | ⬜ Pending  |
| 7     | YOLO object detection integration    | ⬜ Pending  |
| 8     | Evidence engine                      | ⬜ Pending  |
| 9     | API / dashboard                      | ⬜ Pending  |

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/Jaaiwanth/exam-behavior-detection.git
cd exam-behavior-detection
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Add your dataset

See [`dataset/README.md`](dataset/README.md) for the expected folder structure and video format.

---

## Dataset Notice

The real video dataset is **not included** in this repository.  
See [`dataset/README.md`](dataset/README.md) for instructions on preparing your own data.

Only use video data that you have permission to record and process.

---

## Important Limitations

- The current prototype dataset is extremely small (sometimes only one video per class).
- Accuracy figures from a tiny dataset **cannot** be used to claim reliable real-world detection.
- The system does **not** label anyone as a cheater — it reports observable behaviours for human review.
- For production use the dataset must be significantly expanded.

---

## License

This project is for research and educational purposes only.
