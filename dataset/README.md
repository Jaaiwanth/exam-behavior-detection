# Dataset — Exam Behavior Detection

## Why the videos are not included

This repository does **not** contain real video files.

Reasons:
- Videos containing identifiable individuals raise privacy concerns.
- Raw `.mp4` files are large binary assets unsuitable for Git version control.
- Only data you have explicit permission to record and process should be used.

---

## Where to place your dataset

After cloning the repository, place your `.mp4` video files inside the matching sub-directory under `dataset/movements/`.

Each directory already contains a `README.md` placeholder so that Git tracks the folder structure.  
Do **not** delete these placeholder files.

---

## Expected folder structure

```
dataset/
└── movements/
    ├── adjusting_glasses/    ← .mp4 files go here
    ├── drinking_water/
    ├── eye_rubbing/
    ├── scratching_face/
    ├── yawning/
    ├── normal/
    │   ├── looking_at_screen/
    │   └── looking_down/
    └── suspicious/
        ├── looking_behind/
        ├── prolonged_away/
        ├── repeated_left/
        └── repeated_right/
```

---

## Expected video format

| Property     | Recommendation                        |
|--------------|---------------------------------------|
| Container    | `.mp4` (H.264 codec preferred)        |
| Resolution   | 720p (1280×720) or 1080p              |
| Frame rate   | 20–30 fps                             |
| Duration     | ~5 seconds per clip                   |
| Content      | Single subject, front-facing camera   |
| Lighting     | Clear, consistent lighting            |

---

## Naming convention

Files are named automatically by the included `collect_data.py` script:

```
<behavior_name>_001.mp4
<behavior_name>_002.mp4
...
```

If you supply your own videos, follow the same naming pattern for consistency.

---

## Recommended dataset size

| Purpose              | Minimum clips per class | Recommended |
|----------------------|-------------------------|-------------|
| Prototype / pipeline | 1–5                     | —           |
| Functional baseline  | 20–50                   | 50+         |
| Reliable model       | 100+                    | 200+        |

> **Note:** The current prototype dataset is extremely small (sometimes one clip per class).
> Accuracy results from such a dataset **cannot** support claims of reliable detection.

---

## Recording your own dataset

Use the included `collect_data.py` script:

```bash
python collect_data.py
```

The script opens your webcam, lets you select a behaviour, and records a 5-second clip.

---

## Ethical and legal notice

- Only record individuals who have given **informed consent**.
- Do not use data collected in countries or contexts where such recording is prohibited.
- This project is for **research and educational purposes only**.
- Do not use this system to make real disciplinary decisions about individuals.
