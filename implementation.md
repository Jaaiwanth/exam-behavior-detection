# Implementation Log — Exam Behavior Detection

> This document is the project's development log and implementation roadmap.
> It is updated at the end of every phase.

---

## 1. Project Objective

Build an AI-based exam monitoring pipeline that:

- Ingests short (~5 s) webcam videos of exam subjects.
- Extracts facial, hand, and pose landmarks using MediaPipe.
- Engineers temporal numerical features from those landmarks.
- Trains an LSTM to classify **observable behaviours** (not "cheating").
- Feeds classified events into an evidence engine that produces a structured
  activity log for human review.

The system must **not** automatically label anyone as cheating.
It reports observable behaviours; a human reviewer acts on the evidence.

---

## 2. System Architecture

```
Video
  |
OpenCV  (video_reader.py)
  |
MediaPipe - Face + Hands + Pose  (mediapipe_processor.py)
  |
Feature extraction  (feature_extractor.py)
  |
Temporal feature sequences  (temporal_features.py / build_dataset.py)
  |
LSTM behaviour classifier  (train_lstm.py)
  |
Observable behaviour label
  |
Evidence / suspicious-activity engine  (Phase 8)
  |
Optional YOLO object detection  (Phase 7)
  |
Monitoring dashboard  (Phase 9)
```

---

## 3. Dataset Structure

```
dataset/
  movements/
    adjusting_glasses/
    drinking_water/
    eye_rubbing/
    scratching_face/
    yawning/
    normal/
      looking_at_screen/
      looking_down/
    suspicious/
      looking_behind/
      prolonged_away/
      repeated_left/
      repeated_right/
```

Video format: .mp4, ~5 s, 1280x720, 20-30 fps, single subject, front-facing camera.

Real video files are NOT committed to Git.
Each directory contains a README.md placeholder so Git tracks the structure.

---

## 4. Development Phases

| Phase | Description                          | Status      |
|-------|--------------------------------------|-------------|
| 0     | Project setup                        | Complete    |
| 1     | Video ingestion (OpenCV)             | Complete    |
| 2     | MediaPipe landmark extraction        | Complete    |
| 3     | Feature engineering                  | Pending     |
| 4     | Temporal sequence generation         | Pending     |
| 5     | LSTM baseline                        | Pending     |
| 6     | Model evaluation                     | Pending     |
| 7     | YOLO object detection integration    | Pending     |
| 8     | Evidence engine                      | Pending     |
| 9     | API / dashboard                      | Pending     |

---

## 5. Current Phase

Phase 2 - MediaPipe Landmark Extraction - Complete

---

## 6. Completed Phases

### Phase 0 - Project Setup

**Objective:** Establish a clean, GitHub-ready project structure before writing any pipeline code.

#### What was implemented

- Root project directory structure created.
- .gitignore configured to exclude real video files, outputs, model weights,
  Python cache, virtual environments, and editor artefacts.
- README.md - root project overview.
- requirements.txt - all dependencies, grouped by phase, with future phases
  commented out.
- implementation.md - this file; serves as development log and roadmap.
- dataset/README.md - explains exclusion of real videos, expected folder
  structure, video format, naming convention, recommended dataset size, and
  ethics/legal notice.
- Per-behaviour placeholder README.md files in every leaf directory of the
  sample dataset tree so that Git tracks the directory structure without
  committing any actual videos.
- src/README.md - module index.
- outputs/README.md - description of runtime-generated output directories.
- models/README.md - description of model weight storage.
- Existing collect_data.py retained (webcam data collection utility, pre-existing).

#### Files created / modified

| File | Status |
|------|--------|
| .gitignore | Created |
| README.md | Created |
| requirements.txt | Created |
| implementation.md | Created |
| dataset/README.md | Created |
| dataset/movements/adjusting_glasses/README.md | Created |
| dataset/movements/drinking_water/README.md | Created |
| dataset/movements/eye_rubbing/README.md | Created |
| dataset/movements/scratching_face/README.md | Created |
| dataset/movements/yawning/README.md | Created |
| dataset/movements/normal/looking_at_screen/README.md | Created |
| dataset/movements/normal/looking_down/README.md | Created |
| dataset/movements/suspicious/looking_behind/README.md | Created |
| dataset/movements/suspicious/prolonged_away/README.md | Created |
| dataset/movements/suspicious/repeated_left/README.md | Created |
| dataset/movements/suspicious/repeated_right/README.md | Created |
| src/README.md | Created |
| outputs/README.md | Created |
| models/README.md | Created |
| collect_data.py | Pre-existing, retained unchanged |

#### Tests performed

- Verified directory tree with `tree /f` (Windows) - all expected paths present.
- Verified .gitignore pattern `dataset/**/*.mp4` excludes .mp4 files
  while allowing `dataset/**/*.md` placeholder files to be tracked.
- Ran `git status` - all new .md files appear as untracked (ready to stage);
  no .mp4 files appear.

#### Test results

PASS: Directory structure matches specification.
PASS: .gitignore correctly excludes video files.
PASS: Placeholder README.md files are trackable by Git.

#### Problems encountered

None. Pre-existing collect_data.py and dataset/movements/ directories were
already present and consistent with the specification.

#### Solutions

N/A

#### Design decisions

1. .mp4 pattern instead of blanket dataset/ - Using dataset/**/*.mp4 (and
   similar video extensions) rather than dataset/ allows the placeholder
   README.md files inside the dataset tree to be committed. This keeps the
   repository self-documenting without committing any real video data.

2. Per-behaviour README.md instead of .gitkeep - Plain .gitkeep files
   provide no information. A small README.md in each directory explains the
   expected content, making the repository immediately usable by collaborators.

3. requirements.txt phases commented out - Dependencies for phases 7 and 9
   (YOLO, FastAPI) are listed but commented out to keep the initial install lean.

4. No __init__.py in src/ - Scripts will be run directly from the project root
   (e.g., python src/video_reader.py). A package structure can be introduced
   in a later phase if needed.

#### Remaining work

Proceed to Phase 2 - MediaPipe Landmark Extraction.

#### Suggested Git commit message

chore: initialize project structure (Phase 0)

---

### Phase 1 - Video Ingestion

**Objective:** Recursively discover all .mp4 files in the dataset, extract per-video metadata, verify readability, and expose a clean frame-reading API for downstream phases.

#### What was implemented

- `src/video_reader.py` created with the following public API:
  - `discover_videos(root, extensions)` - recursively finds all video files under root, returns sorted list of Path objects.
  - `read_video_metadata(video_path)` - extracts FPS, frame count, duration, resolution; returns a VideoMetadata dataclass; never crashes on bad input.
  - `scan_dataset(root)` - batch scan: calls discover + metadata for every video.
  - `read_frames(video_path, max_frames)` - generator yielding (frame_index, frame) tuples in chronological order.
  - `save_metadata_csv(metadata, output_path)` - writes metadata list to CSV.
  - `print_summary(metadata)` - formatted terminal report with prototype warning.
- `VideoMetadata` dataclass captures: path, label, fps, frame_count, duration_s, width, height, readable, error.
- Label is derived from the immediate parent directory name (e.g. eye_rubbing, repeated_left).
- Works with both dataset layouts present in the repository:
  - `dataset/movements/<behavior>/`
  - `dataset/normal/<behavior>/` and `dataset/suspicious/<behavior>/`
- CLI entry point: `python src/video_reader.py --dataset dataset --output outputs/metadata.csv`

#### Files created / modified

| File | Status |
|------|--------|
| `src/video_reader.py` | Created |
| `outputs/metadata.csv` | Generated at runtime (not committed) |
| `implementation.md` | Updated |

#### Tests performed

1. Ran `python src/video_reader.py --dataset dataset --output outputs/metadata.csv`
2. Verified all 11 videos reported as readable with no errors.
3. Verified CSV written correctly with all expected columns.
4. Verified the FPS fallback warning path is documented (triggered when FPS <= 0).
5. Verified error path: the function returns a failed VideoMetadata rather than raising on bad input.

#### Test results

```
Total: 11 videos | Readable: 11 | Failed: 0

All videos: 20.0 fps, 1280x720, ~7.3-7.5 seconds, 146-150 frames
```

CSV file written to outputs/metadata.csv with correct headers and values.

#### Problems encountered

None. All 11 videos opened successfully on first attempt.

#### Solutions

N/A

#### Design decisions

1. VideoMetadata dataclass, not a plain dict - strongly typed, IDE-friendly,
   serializable with dataclasses.asdict().

2. Label from parent directory name - the immediate parent directory always
   names the behaviour class regardless of which sub-tree the video lives in.
   This handles both dataset/movements/eye_rubbing/ and dataset/suspicious/repeated_left/.

3. read_frames() as a generator, not a list - avoids loading all frames into
   memory at once. A 150-frame 1280x720 video is ~328 MB as raw BGR arrays.

4. Graceful failure in read_video_metadata() - returns a failed VideoMetadata
   rather than raising an exception, so a batch scan continues past bad files.

5. Sorted discovery order - ensures deterministic processing order across
   machines and OS file systems.

#### Remaining work

Proceed to Phase 2 - MediaPipe Landmark Extraction.

#### Suggested Git commit message

feat: add video ingestion pipeline (Phase 1)

---

### Phase 2 - MediaPipe Landmark Extraction

**Objective:** Extract structured face, hand, and pose landmarks from every frame of every video using the MediaPipe Tasks API (mediapipe 1.0+).

#### What was implemented

- `src/mediapipe_processor.py` created with:
  - `LandmarkProcessor` class (context manager) using:
    - `FaceLandmarker` (478 landmarks, VIDEO mode, head pose via solvePnP)
    - `HandLandmarker` (21 landmarks per hand, VIDEO mode)
    - `PoseLandmarker` (33 landmarks, VIDEO mode)
  - `FaceResult` dataclass: landmarks (478x3), face_center, left/right eye centers, nose tip, mouth center, yaw/pitch/roll, bbox_px.
  - `HandResult` dataclass: landmarks (21x3), handedness, wrist, index_tip, middle_tip, ring_tip, pinky_tip, hand_center.
  - `PoseResult` dataclass: landmarks (33x4), named upper-body points (nose, shoulders, elbows, wrists).
  - `FrameLandmarks` container: face + left_hand + right_hand + pose per frame.
  - `process_frame(frame_bgr, frame_index)` - single-frame entry point.
  - `process_video(video_path, max_frames)` - processes entire video, returns List[FrameLandmarks].
  - Head pose estimation via OpenCV solvePnP with 6-point anatomical face model.
  - Graceful handling: all missing detections return detected=False with None fields.
- `src/visualize_landmarks.py` created with:
  - `annotate_frame(frame_bgr, result)` - returns annotated frame with all landmarks drawn.
  - `draw_face()` - eye highlights (green/orange), nose, mouth, face center crosshair, head pose axes.
  - `draw_hands()` - skeleton + color-coded fingertips (L=green, R=red).
  - `draw_pose()` - upper-body skeleton.
  - `draw_hud()` - semi-transparent status panel (frame index, detection status, yaw/pitch/roll).
  - `run_live()` - live window mode.
  - `run_save()` - writes annotated video to file.
- `setup_models.py` created:
  - Downloads face_landmarker.task (3.6 MB), hand_landmarker.task (7.5 MB), pose_landmarker.task (5.5 MB) from Google CDN.
  - Skips already-downloaded files.

**Important Python version note:** mediapipe 1.0+ requires Python 3.10-3.12. This project uses Python 3.11.
All scripts must be run with `py -3.11` on machines with Python 3.14 as default.

#### Files created / modified

| File | Status |
|------|--------|
| `src/mediapipe_processor.py` | Created |
| `src/visualize_landmarks.py` | Created |
| `setup_models.py` | Created |
| `models/face_landmarker.task` | Downloaded (not committed) |
| `models/hand_landmarker.task` | Downloaded (not committed) |
| `models/pose_landmarker.task` | Downloaded (not committed) |
| `.gitignore` | Updated (added *.task) |
| `requirements.txt` | Updated (Python version note) |
| `implementation.md` | Updated |

#### Tests performed

1. Ran `py -3.11 setup_models.py` - downloaded all 3 model files.
2. Ran `py -3.11 src/mediapipe_processor.py --video dataset/movements/eye_rubbing/eye_rubbing_001.mp4`.
3. Verified face detection on all 150 frames.
4. Verified hand detection (right hand dominant for eye rubbing - expected).
5. Verified pose detection on all 150 frames.
6. Verified head pose angles are physically plausible (yaw ~+5deg, pitch ~-16deg, roll ~-12deg for looking slightly down).

#### Test results

```
eye_rubbing_001.mp4 | 150 frames | face 150/150 | L-hand 20/150 | R-hand 123/150 | pose 150/150

Detection rates over 150 frames:
  Face:       100.0%
  Left hand:   13.3%
  Right hand:  82.0%   <- dominant hand rubbing right eye
  Pose:       100.0%

Head pose (frame 0): Yaw=+5.1deg  Pitch=-17.6deg  Roll=-11.8deg
```

Results are physically plausible for the eye_rubbing behaviour (subject looking slightly down-right, right hand near eye).

#### Problems encountered

1. mediapipe 1.0.1 removed the legacy mp.solutions API entirely.
   Initial implementation used the old API and failed to import.

2. Default Python on this machine is 3.14; mediapipe requires 3.10-3.12.
   pip install was initially targeting Python 3.14 and failing silently.

3. ModuleNotFoundError for 'src' when running scripts directly with py -3.11.

#### Solutions

1. Rewrote mediapipe_processor.py to use the Tasks API (FaceLandmarker,
   HandLandmarker, PoseLandmarker with VIDEO running mode).

2. Used `py -3.11 -m pip install mediapipe` to target Python 3.11 explicitly.
   Updated requirements.txt with a clear Python version warning.

3. Added sys.path.insert at the top of each script to add the project root.

#### Design decisions

1. Tasks API (mediapipe 1.0+) over legacy solutions API - future-proof;
   the legacy API is fully removed in 1.0+.

2. VIDEO running mode, not IMAGE mode - enables landmark tracking across
   frames (lower jitter, better temporal consistency for the LSTM).

3. Timestamp = frame_index * 33ms - assumes ~30fps spacing for the video
   timeline. This is a simplification but sufficient for VIDEO mode tracking.

4. HAND_CONNECTIONS defined as a module-level constant - avoids dependency
   on mp.solutions.hands in the visualizer.

5. setup_models.py as a separate utility - model files are large binary
   assets that should not be downloaded automatically during import.

#### Remaining work

Proceed to Phase 3 - Feature Engineering.

#### Suggested Git commit message

feat: add MediaPipe landmark extraction (Phase 2)

---

## 7. Pending Phases

- Phase 3 - Feature engineering
- Phase 4 - Temporal sequence generation
- Phase 5 - LSTM baseline
- Phase 6 - Model evaluation
- Phase 7 - YOLO object detection integration
- Phase 8 - Evidence engine
- Phase 9 - API / dashboard

---

## 8. Design Decisions

| Decision | Rationale |
|----------|-----------|
| Observable behaviour labels, not "cheating" | Prevents false accusation; keeps model in its competence boundary |
| LSTM over CNN-only | Temporal sequence is essential; hand approach patterns unfold over time |
| MediaPipe over raw CNN detector | Provides structured, normalizable landmarks without training a detector |
| Normalize distances to face/body size | Handles different camera distances and subject sizes |
| All windows from one video stay in same split | Prevents data leakage - overlapping windows are not independent samples |

---

## 9. Known Limitations

- Tiny dataset: The current prototype has as few as one video per class.
  Accuracy figures from this dataset cannot be used to claim generalization.
- Single subject: All current recordings are of one individual.
  The model will not generalize across subjects without a much larger dataset.
- Controlled conditions: Current recordings use consistent lighting and
  background. Real exam environments vary significantly.
- No real-time pipeline yet: The current architecture processes pre-recorded
  video files. Live inference will require optimization.
- No evidence engine yet: The LSTM output is not yet connected to a
  structured event/suspicion system.

---

## 11. Suggested Git Commits

| Phase | Suggested commit message |
|-------|--------------------------|
| 0 | chore: initialize project structure (Phase 0) |
| 1 | feat: add video ingestion pipeline (Phase 1) |
| 2 | feat: add MediaPipe landmark extraction (Phase 2) |
| 3 | feat: add feature engineering (Phase 3) |
| 4 | feat: add temporal sequence generation (Phase 4) |
| 5 | feat: add LSTM behaviour classifier (Phase 5) |
| 6 | feat: add model evaluation (Phase 6) |
| 7 | feat: add YOLO object detection integration (Phase 7) |
| 8 | feat: add evidence engine (Phase 8) |
| 9 | feat: add API and monitoring dashboard (Phase 9) |

---

## 12. Testing Log

| Phase | Test | Result | Notes |
|-------|------|--------|-------|
| 0 | Directory tree verification | PASS | All 16 expected paths present |
| 0 | .gitignore video exclusion | PASS | 0 .mp4 files staged |
| 0 | .gitignore README inclusion | PASS | All placeholder README.md files staged |
| 1 | scan_dataset() on 11 real videos | PASS | 11/11 readable, 0 failed |
| 1 | CSV output written | PASS | outputs/metadata.csv contains correct headers and values |
| 1 | Label derivation | PASS | Labels match parent directory names |
| 1 | Frame generator | PASS | read_frames() yields (index, frame) without crashing |
