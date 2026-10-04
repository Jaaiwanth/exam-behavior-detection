# ExamProctor — Progress Report (Phases B–E)

Everything built in this session on top of Phase A (authentication). All of it compiles
(`npm run build` passes) but **has not been tested end-to-end against live Firestore / the
FastAPI backend / DynamoDB.** Treat each phase as "built, needs manual verification".

---

## 1. Summary

| Phase | What it covers | Status |
|-------|----------------|--------|
| A — Authentication | Landing, student/mentor signup + login, admin approval | Already existed; one login race fixed (see §7) |
| B — Course & exam setup | Courses, exams, Excel question upload, go-live toggle | Built |
| C — Student exam flow | Camera gate, fullscreen, timer, monitoring, submit | Built |
| D — Results & analytics | Result page with 4 charts, exam history | Built |
| E — Mentor dashboard | Student management, per-student results, leaderboard, behaviour log, live link | Built |
| Firestore rules | Security rules draft | Drafted, **not deployed** |
| S3 CORS | Presigned-URL config | Deferred |

---

## 2. Phase B — Course and Exam Setup

**Mentor can:**
- Create courses (**My Courses** tab → **+ New Course**).
- Create exams inside a course: title, number of questions to pick per student, duration in minutes.
- Upload a question bank from Excel (`.xlsx`, `.xls`, `.csv`). Columns: Question, Option A–D, Correct (A/B/C/D), Topic (optional).
  - Invalid rows (bad answer letter, missing options) are skipped with a warning instead of silently defaulting to "A".
  - Re-uploading replaces the existing bank.
- Make an exam live or close it. An exam cannot go live with an empty bank or if `pick_n` is larger than the bank.
- Create-course / create-exam failures now show an error message instead of leaving the button stuck.

**Files:** `frontend/src/pages/MentorDashboard.jsx`, `frontend/src/api/examApi.js`, dashboard styles in `frontend/src/index.css`
(the dashboard classes were missing from the CSS entirely and had to be written).

---

## 3. Phase C — Student Exam Flow

**Route:** `/exam/:examId` (students only) — `frontend/src/pages/ExamRoom.jsx`, `frontend/src/components/Timer.jsx`.

1. **Pre-flight checks:** exam exists, student is enrolled, not already submitted, exam is live (unless the student already has a session).
2. **Start screen:** one button requests camera access, then fullscreen, then assigns a random N-question subset (saved in Firestore, so a refresh keeps the same questions).
3. **During the exam:**
   - One question at a time with numbered jump buttons.
   - Small camera preview. Frames stream at ~2 FPS to the ML backend over `/ws/student/{uid}?exam_id=…`.
   - The student does **not** see their integrity score or warnings.
   - Every answer is saved to Firestore as it is picked.
   - Leaving fullscreen shows a "return to fullscreen" overlay (the timer keeps running).
   - Timer counts down to a fixed end time derived from the saved start time, so **refreshing does not reset it**.
4. **Submit:** confirm dialog, or auto-submit at zero. Pending answer saves are flushed first, then the exam is scored.

---

## 4. Phase D — Results and Analytics

**Routes:** `/results/:examId`, `/student/history` (students only).

Result page shows:
1. Overall score ring + correct/wrong counts + rank among everyone who took the exam
2. Topic-wise bars (weakest first)
3. Score trend across the student's exams (needs 2+ exams)
4. Per-question answer review (correct / wrong / skipped)

Charts are plain SVG — no chart library added.
**Exam History** lists past results; each row opens its result page.
The leaderboard now sorts in the browser (no Firestore composite index needed); equal scores share a rank.

**Files:** `pages/Results.jsx`, `pages/StudentHistory.jsx`, `components/ResultsView.jsx`, `ScoreGauge.jsx`, `TopicChart.jsx`, `TrendChart.jsx`.

---

## 5. Phase E — Mentor Dashboard

**Architecture change you requested:** students can **no longer enroll themselves**. The mentor adds them.

- **Students tab** (course → **👥 Students**): paste registration numbers or emails (one per line or comma-separated). Each entry reports added / not found / already in course. Students must have signed up first. Remove button per student.
- Student dashboard shows only courses the student was added to; the "Available Courses / Enroll Now" section is gone.
- **Per-student view** (Students → **Results**): the student's exams with scores, and for any exam the same four charts + answer review, plus the **Behaviour Log**.
- **Leaderboard** on the exam detail page shows student names instead of uids.
- **🔴 Live** button opens the existing live monitor at `/mentor/live/:studentId`.

**Backend changes** (`backend/main.py`, `backend/dynamo_logger.py`):
- New `GET /api/events/{student_id}?exam_id=` reads warning events from DynamoDB.
- The student WebSocket accepts `?exam_id=` and stores it on each logged event so events can be filtered per exam.
- Frontend: `frontend/src/api/events.js`, `frontend/src/components/StudentDetail.jsx`.

---

## 6. Firestore security rules (drafted, not deployed)

`firestore.rules` in the repo root. Prevents users promoting their own role, students writing enrollments/exams/courses, writing another student's session or result, and editing a submitted exam.

**Not covered** (needs backend/Cloud Functions): the browser still computes and writes the score; question banks include correct answers and are readable by any signed-in user; any signed-in user can read results.

To use: Firebase Console → Firestore → Rules → paste → Publish, then re-test every flow.
**Reminder:** test mode expires (usually 30 days) and then all reads/writes fail. Check the date in the Rules tab.

---

## 7. Other fixes

- **Login redirect bug:** logging in as a mentor sent you straight back out. `AuthContext` now waits until the role is fetched before the route guards decide.
- **`/student/history` redirect:** it used to hit the catch-all route and look like a logout; the page now exists.
- `frontend/.env` points at the EC2 server (`13.203.194.156:8000`), not localhost.

---

## 8. Manual test checklist

1. Sign up as mentor → approve (Firestore Console: `users/{uid}.role = "mentor"`) → log in.
2. Create course → create exam → upload Excel → Go Live.
3. Sign up a student (verify email) → mentor adds them in Students tab.
4. Student: log in → open course → Start Exam → answer → refresh (should resume) → submit.
5. Student: View Results, Exam History.
6. Mentor: Students → Results → exam (charts + behaviour log); leaderboard names; Live button.
7. Restart the backend first: `py -3.11 -m uvicorn backend.main:app --reload --port 8000`.

---

## 9. Known limitations / still to do

- Score is computed in the browser; questions + correct answers are sent to the student's browser (needs a backend grading endpoint to fix).
- `/api/events` has no authentication — anyone who knows a student uid can read their events.
- Fullscreen exits are not logged to DynamoDB; the exam end time is not enforced server-side.
- Events logged before this work have `session_id = "default"` and won't appear under any exam.
- Mentors cannot yet bulk-import students from Excel.
- Student login looks the account up by the email field (the `reg_map` collection is never written), so the registration number is not actually checked.
- S3 CORS for presigned clip URLs: not started.
- `implementation.md` (ML pipeline status) is out of date — it still says Phase 3 is current.
- Pre-existing lint warnings in `StudentExam.jsx` (old prototype page, no longer routed) and `useEffect` dependency warnings in the dashboards.

---

## 9b. Update — Manual review pipeline

Added after the first version of this report. Full description in `PLATFORM_IMPLEMENTATION.md` §12.

- Score 0 now only flags the session as **Pending Review**. Nothing fails, punishes or submits the student; the mentor decides (**Cleared** / **Confirmed Violation**, with notes, reviewer and time stored).
- Each warning produces a DynamoDB event and a private S3 MP4 clip (6 s before + 4 s after). Mentors watch it through a 5-minute presigned URL requested from the backend.
- The events API is now authenticated (Firebase ID token), mentor/admin only, and mentors can only see exams they created. This closes the "no authentication on /api/events" item in §9.
- Verified by `backend/tests/test_review_pipeline.py` against moto (3 tests pass). **Not** verified against real AWS or a real browser.
- **DynamoDB schema:** the logger now matches `infra/dynamo_setup.py` (PK `exam_id`). If your existing `exam_events` table was created with a different key (e.g. PK `student_id`), it must be recreated.
- New backend deps: `google-auth`, `requests`, `imageio-ffmpeg` (`backend/requirements_web.txt`); tests: `backend/requirements_test.txt`.
- The `/ws/faculty/{student_id}` live feed is still unauthenticated.

## 10. Git state

Nothing was committed or pushed by Claude (per your instruction). Uncommitted changes at the time of writing:

```
 M PLATFORM_IMPLEMENTATION.md
 M backend/dynamo_logger.py
 M backend/main.py
 M frontend/src/api/examApi.js
 M frontend/src/main.jsx
 M frontend/src/pages/ExamRoom.jsx
 M frontend/src/pages/MentorDashboard.jsx
 M frontend/src/pages/Results.jsx
?? firestore.rules
?? frontend/src/api/events.js
?? frontend/src/components/ResultsView.jsx
?? frontend/src/components/StudentDetail.jsx
```

Suggested commit messages (see `PLATFORM_IMPLEMENTATION.md` §11):
- `feat(mentor): per-student results, behaviour log, live link`
- `feat(mentor): mentor-managed course enrollment`
- `docs: add firestore security rules draft and progress report`
