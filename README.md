# ExamProctor

An AI-proctored online examination platform. Students take timed MCQ exams in the browser while a
real-time computer-vision pipeline watches the webcam feed. Suspicious behaviour is **flagged, never
auto-punished**: a mentor reviews the recorded warning clips and makes the final decision.

> **Design rule:** an integrity score of 0 means *"needs manual review"*, not *"cheating"*. The system
> never fails, penalises or auto-submits a student. Only a mentor's decision (Cleared / Confirmed
> Violation) is final.

## How it works

```
Student browser (React)                    FastAPI backend (Python 3.11)               AWS
┌────────────────────────┐   WebSocket     ┌────────────────────────────┐
│ ExamRoom + camera hook │ ── frames ────► │ student_ws                 │
│  (1 stream, ~2 FPS)    │ ◄─ calibration ─│  └─ ExamMonitor (real ML)  │──► DynamoDB  exam_events
└────────────────────────┘                 │      MediaPipe · dlib ·    │──► S3 (private) warning clips
                                           │      YOLOv8n               │
Mentor browser (React)      REST + token   │ review API                 │
┌────────────────────────┐ ◄────────────►  │  events · recording URL ·  │──► presigned URL (5 min)
│ Behaviour review       │                 │  review decision           │
└────────────────────────┘                 └────────────────────────────┘
        Firebase Auth + Firestore  (users, courses, exams, questions, results)
```

1. A warning is raised by the real-time monitor (head turned away, face not visible, a different
   person, a phone / laptop / extra person / book in frame).
2. The backend writes an event to **DynamoDB** and encodes a short MP4 clip (6 s before + 4 s after)
   to a **private S3** bucket.
3. When the score reaches 0 the student's exam session becomes **Pending Review**. The student
   can keep working.
4. The mentor opens the behaviour log, plays a clip through a **short-lived presigned URL**, and
   records Cleared or Confirmed Violation (with notes, reviewer and time).

The student browser never sees the score, the warnings, S3 keys or recording URLs.

## Roles

| Role | Can do |
|------|--------|
| **Student** | Take exams for courses a mentor added them to; view results and history |
| **Mentor** | Create courses and exams, upload question banks (Excel), manage students, view results, leaderboard, review flagged sessions and recordings, watch a live feed |
| **Admin** | Approve or reject mentor sign-ups |

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, Vite, React Router |
| Auth / app data | Firebase Authentication + Firestore |
| Backend | FastAPI, WebSockets (Python 3.11) |
| Monitoring | MediaPipe (face / pose / hands), dlib (face identity), YOLOv8n (objects) |
| Events | AWS DynamoDB (`exam_events`) |
| Recordings | AWS S3, private bucket + presigned URLs |

## Repository layout

```
backend/        FastAPI app: WebSocket monitoring, review API, Firebase token auth,
                DynamoDB / S3 helpers, clip recorder
  tests/        unit tests (moto) and the real-browser e2e script
frontend/       React app (exam room, dashboards, results, mentor review)
infra/          DynamoDB table setup, EC2 IAM policy, AWS connectivity + e2e checks
src/            ML detectors used by the backend (mediapipe_processor, face_verifier, object_detector)
models/         MediaPipe .task files (downloaded by setup_models.py, not committed)
setup_models.py downloads the MediaPipe model files
firestore.rules Firestore security rules (draft — review before deploying)
requirements.txt        runtime dependencies (local + server)
requirements-dev.txt    tests and development tools
PLATFORM_IMPLEMENTATION.md   design, data model, API and protocol reference
PROGRESS_REPORT.md           build / verification log
```

## Setup

### Prerequisites
Python **3.11** (not 3.12+, MediaPipe constraint), Node.js 18+, a Firebase project, an AWS account
(`ap-south-1` by default).

### 1. Backend
```bash
py -3.11 -m pip install -r requirements.txt
py -3.11 setup_models.py            # downloads the MediaPipe .task files into models/
```
YOLOv8n weights (`yolov8n.pt`) are downloaded automatically by Ultralytics on first run, into the
folder you start the backend from — **start it from the repository root**.

### 2. AWS resources
```bash
py -3.11 infra/dynamo_setup.py      # creates the exam_events table (PAY_PER_REQUEST)
```
Create a **private** S3 bucket named `jaaiwanth-exam-monitor-recordings` (or set `RECORDING_BUCKET`)
with Block Public Access and default encryption enabled:
```bash
aws s3api create-bucket --bucket <name> --region ap-south-1 \
    --create-bucket-configuration LocationConstraint=ap-south-1
aws s3api put-public-access-block --bucket <name> --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket <name> --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```
`infra/ec2_iam_policy.json` is the least-privilege policy for the server's IAM role.
`py -3.11 infra/test_aws.py` verifies DynamoDB and S3 access.

### 3. Firebase
Enable **Email/Password** auth and create a Firestore database. The web config lives in
`frontend/src/firebase.js`. Draft security rules are in `firestore.rules` (publish them from the
Firebase console and re-test every flow; test mode expires).

**First admin:** sign up through the Mentor form, then in Firestore set `users/{uid}.role` to
`"admin"`. Approve other mentors at `/admin`.

### 4. Frontend
```bash
cd frontend
npm install
```
Create `frontend/.env` (gitignored):
```
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

## Run

```bash
# Terminal 1 — backend (from the repository root)
py -3.11 -m uvicorn backend.main:app --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev          # http://localhost:5173
```

### Backend environment variables
| Variable | Default | Purpose |
|----------|---------|---------|
| `AWS_REGION` | `ap-south-1` | AWS region |
| `DYNAMO_TABLE` | `exam_events` | DynamoDB table |
| `RECORDING_BUCKET` | `jaaiwanth-exam-monitor-recordings` | S3 bucket for warning clips |
| `PRESIGN_EXPIRES_SEC` | `300` | Lifetime of recording URLs |
| `FIREBASE_PROJECT_ID` | `exam-proctor-31750` | Used to verify Firebase ID tokens |
| `WS_AUTH` | `1` | `0` skips WebSocket token checks — **local test harness only, never in production** |

## Tests

```bash
py -3.11 -m pip install -r requirements-dev.txt
py -3.11 -m pytest backend/tests -q          # 8 tests, in-memory AWS (moto)
cd frontend && npm run build && npm run lint
```
`backend/tests/e2e_browser_proctor.py` is a real-browser, real-ML, real-AWS end-to-end run
(headless Chromium with a fake webcam). It is not part of the pytest suite; see the script header.
`infra/test_review_e2e_aws.py` checks the review pipeline against real AWS.

## Security notes
- Students and mentors authenticate with Firebase. The backend verifies the Firebase ID token on every
  review API call and on both WebSockets; mentors can only access exams they created.
- Recordings are private. The browser only ever receives a presigned URL that expires in minutes.
- Students cannot send `reset` / `recalibrate`; those are staff-only actions.
- Known limits: grading runs in the browser and question banks (with correct answers) are readable by
  signed-in users; Firestore rules are a draft. See `PLATFORM_IMPLEMENTATION.md` and `PROGRESS_REPORT.md`.
