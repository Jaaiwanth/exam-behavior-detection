# ExamProctor — Web Platform Implementation

> This document tracks the design, architecture, and build status of the
> full-stack exam web platform that wraps the AI behaviour-monitoring backend.
> The ML pipeline is documented separately in `implementation.md`.

---

## 1. Platform Overview

An end-to-end AI-proctored online examination platform with three user roles:

| Role | Access |
|------|--------|
| **Student** | Register, take exams, view results & history |
| **Mentor** | Upload questions, create exams, view student analytics |
| **Admin** (Jaaiwanth) | Approve/reject mentor signup requests |

---

## 2. Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19 + Vite + React Router v7 |
| Styling | Vanilla CSS (dark glassmorphism design system) |
| Auth | Firebase Authentication (Email/Password) |
| Database | Firebase Firestore (user profiles, courses, exams, results) |
| Behaviour events | AWS DynamoDB (`exam_events` table) |
| Video clips | AWS S3 (`jaaiwanth-exam-monitor-recordings`) |
| ML backend | FastAPI + WebSocket (Python 3.11, EC2) |
| Notifications | (Optional) AWS SES for email alerts |

---

## 3. System Architecture

```
Browser (React)
  │
  ├── Firebase Auth ──────────────────► Firestore
  │     (login / signup)                (users, courses, exams,
  │                                      questions, results)
  │
  ├── REST API ───────────────────────► FastAPI (EC2)
  │     GET  /api/quiz                   (ML backend)
  │     POST /api/submit
  │
  └── WebSocket ──────────────────────► FastAPI (EC2)
        WS /ws/student/{id}              (frame analysis)
        WS /ws/faculty/{id}              (live faculty feed)
```

---

## 4. Firestore Data Model

```
users/
  {uid}/
    name          String
    email         String
    role          "student" | "mentor" | "pending" | "admin" | "rejected"
    reg_no        String   (students only)
    created_at    ISO timestamp

pending_mentors/
  {uid}/
    name          String
    email         String
    uid           String
    requested_at  ISO timestamp
    status        "pending" | "approved" | "rejected"

courses/
  {courseId}/
    name          String         e.g. "AWS Cloud Architect"
    mentor_uid    String
    created_at    ISO timestamp

enrollments/
  {courseId}__{uid}/
    student_uid   String
    course_id     String
    enrolled_at   ISO timestamp

exams/
  {examId}/
    course_id     String
    title         String
    total_q       Number         total questions in bank
    pick_n        Number         random questions to assign each student
    duration_sec  Number         e.g. 600 (10 min)
    is_live       Boolean
    created_by    String         mentor uid
    created_at    ISO timestamp

questions/
  {examId}/bank/{questionId}/
    question      String
    opt_a         String
    opt_b         String
    opt_c         String
    opt_d         String
    correct       "A" | "B" | "C" | "D"
    topic         String         e.g. "Trees", "Graphs"

student_exams/
  {examId}__{studentUid}/
    question_ids  Array          shuffled subset picked for this student
    answers       Map            { questionId: "A" | "B" | ... }
    submitted     Boolean
    started_at    ISO timestamp
    submitted_at  ISO timestamp
    score         Number
    topic_scores  Map            { "Trees": { correct: 3, total: 5 }, ... }

results/
  {examId}__{studentUid}/
    score         Number
    total         Number
    percentage    Number
    rank          Number
    topic_scores  Map
    exam_title    String
    submitted_at  ISO timestamp
```

---

## 5. Feature Roadmap

### Phase A — Authentication (In Progress)

| Feature | Status | Notes |
|---------|--------|-------|
| Landing page (role selector) | Done | `LandingPage.jsx` |
| Student signup | Done | Name + Reg No + Email + Password |
| Student email verification | Done | Firebase `sendEmailVerification` |
| Student login | Done | Email + Password + role check |
| Mentor signup | Done | role = "pending" on creation |
| Mentor approval flow | Done | Writes to `pending_mentors` collection |
| Admin approval panel | Done | `/admin` approve/reject UI |
| Auth context (global state) | Done | `AuthContext.jsx` + `useAuth()` |
| Protected routes | Done | Role-based redirect in `main.jsx` |

---

### Phase B — Course and Exam Setup (Done — needs manual test)

| Feature | Status | Notes |
|---------|--------|-------|
| Course creation by mentor | Done | Single course: "AWS Cloud Architect" |
| Student enrollment to course | Done | `StudentDashboard.jsx` |
| Excel upload (question bank) | Done | 6-col format |
| Question bank stored in Firestore | Done | `questions/{examId}/bank/` |
| Exam creation (title, pick N, duration) | Done | Mentor sets random pick count |
| Make exam live / close | Done | Toggle `is_live` flag |

**Excel upload format (6 columns):**

| Col 1 | Col 2 | Col 3 | Col 4 | Col 5 | Col 6 | Col 7 (optional) |
|-------|-------|-------|-------|-------|-------|------|
| Question | Option A | Option B | Option C | Option D | Correct (A/B/C/D) | Topic |

Invalid rows (bad answer letter / missing options) are skipped with a warning. An exam can't go live with an empty bank or `pick_n` > bank size.

---

### Phase C — Student Exam Flow (Done — needs manual test)

| Feature | Status | Notes |
|---------|--------|-------|
| Course list and enrolled course | Done | Student dashboard |
| Exam list (live/closed indicator) | Done | Under each course |
| Webcam permission gate | Done | Before exam starts |
| Fullscreen lock on exam start | Done | `requestFullscreen()` API |
| Random N-of-bank question assignment | Done | Seeded per student, stored in Firestore |
| MCQ exam UI (20 questions) | Done | All questions scrollable |
| Countdown timer (10 min) | Done | Auto-submit on expiry |
| ML monitoring via WebSocket | Exists | `monitor_session.py` + `main.py` done |
| Behaviour count logged silently | Exists | DynamoDB `exam_events` table |
| Student sees only question + webcam | Done | Hide score/warnings during exam |
| Manual submit | Done | Submit button + confirm dialog |
| Auto submit on timer expiry | Done | `setTimeout` triggers submit |

---

### Phase D — Results and Analytics (Done — needs manual test)

| Feature | Status | Notes |
|---------|--------|-------|
| Answer evaluation on submit | Done | Compare to `correct` in Firestore |
| Score calculation | Done | Correct / total x 100 |
| Topic-wise breakdown | Done | Group by `topic` field per question |
| Result stored in Firestore | Done | `results/{examId}__{uid}` |
| Student result page | Done | Score + 4 visual charts |
| Exam history page | Done | Past exam results list |

**4 Visuals on student result page:**

1. **Overall score gauge** — circular progress ring (e.g. 72%)
2. **Topic-wise bar chart** — e.g. Trees 60%, Graphs 10%
3. **Performance trend line** — score across past exams
4. **Answer review** — per-question correct/wrong breakdown

---

### Phase E — Mentor Dashboard (Pending)

| Feature | Status | Notes |
|---------|--------|-------|
| Student list per course | Pending | Firestore enrollments query |
| Per-student result view | Pending | Same 4 charts for any student |
| Leaderboard per exam | Pending | Ranked by score descending |
| Live monitoring | Exists | Faculty WebSocket in `main.py` |
| Behaviour event log per student | Pending | DynamoDB query on `exam_events` |

---

## 6. File Structure (Frontend)

```
frontend/src/
  firebase.js                  Firebase init (Auth + Firestore)
  main.jsx                     Routing + AuthProvider wrapper
  index.css                    Global design system + page styles

  context/
    AuthContext.jsx             useAuth() hook — user, role, loading

  pages/
    LandingPage.jsx             Role selector (Student / Mentor)       [Done]
    StudentAuth.jsx             Student signup + login                  [Done]
    MentorAuth.jsx              Mentor signup + login                   [Done]
    AdminApproval.jsx           Admin approve/reject mentors            [Done]
    StudentExam.jsx             Exam taking page                        [Existing]
    FacultyDashboard.jsx        Live monitoring dashboard               [Existing]
    StudentDashboard.jsx        Course list, exam list                  [Done]
    MentorDashboard.jsx         Full mentor panel                       [Done]
    ExamRoom.jsx                Fullscreen exam with timer              [Done]
    Results.jsx                 Score + charts                          [Done]

  components/
    MonitoringStatus.jsx        Behaviour monitoring indicator          [Existing]
    QuizQuestion.jsx            Single MCQ card                        [Existing]
    Timer.jsx                   Countdown timer                         [Done]
    TopicChart.jsx              Topic-wise bar chart                    [Done]
    ScoreGauge.jsx              Circular score ring                     [Done]
    TrendChart.jsx              Score trend line                        [Done]
    Leaderboard.jsx             Rank table                              [Todo]

  api/
    examApi.js                  Firestore read/write helpers            [Todo]
```

---

## 7. Admin Setup (One-time)

### 7.1 Make yourself Admin in Firestore

1. Sign up using the **Mentor** flow with your email
2. Go to **Firebase Console → Firestore → users → {your-uid}**
3. Change `role` field from `"pending"` to `"admin"`
4. Done — `/admin` route is now accessible to your account

### 7.2 DynamoDB Table

Already set up via AWS Console. Table name: `exam_events` in `ap-south-1`.

### 7.3 Firebase Console Checklist

- [x] Project created: `exam-proctor-31750`
- [x] Email/Password auth enabled
- [x] Firestore database created (test mode)
- [ ] Firestore security rules (tighten before production)
- [ ] S3 bucket CORS config for presigned URLs

---

## 8. Routes

| Path | Component | Access |
|------|-----------|--------|
| `/` | LandingPage | Public |
| `/student/login` | StudentAuth | Public |
| `/mentor/login` | MentorAuth | Public |
| `/admin` | AdminApproval | Admin only |
| `/student/dashboard` | StudentDashboard | Student only |
| `/exam/:examId` | ExamRoom | Student only |
| `/results/:examId` | Results | Student only |
| `/mentor/dashboard` | MentorDashboard | Mentor / Admin |

---

## 9. Running Locally

```powershell
# Terminal 1 — Frontend
cd frontend
npm run dev
# Opens at http://localhost:5173

# Terminal 2 — Backend (ML + API)
py -3.11 -m uvicorn backend.main:app --reload --port 8000
# Opens at http://localhost:8000
```

---

## 10. Build Status Summary

```
Phase A — Auth          85%   Routes, pages, Firebase auth all done
Phase B — Exam setup    90%   Mentor dashboard + examApi + student enroll done; untested against live Firestore
Phase C — Exam room     90%   ExamRoom + Timer done; untested end-to-end with backend
Phase D — Results       90%   Results page, 4 charts, history done; untested with live data
Phase E — Mentor dash   10%   Live feed exists, analytics pending
```

---

## 11. Git Commit Conventions

| Phase | Prefix | Example |
|-------|--------|---------|
| Auth | `feat(auth):` | `feat(auth): add student signup with Firebase` |
| Exam setup | `feat(exam):` | `feat(exam): excel question bank upload` |
| Exam room | `feat(room):` | `feat(room): fullscreen lock + timer` |
| Results | `feat(results):` | `feat(results): topic-wise chart` |
| Mentor | `feat(mentor):` | `feat(mentor): leaderboard view` |
| Fixes | `fix:` | `fix: mentor pending role check on login` |
