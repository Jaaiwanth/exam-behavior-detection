/* src/pages/ExamRoom.jsx — Proctored exam: camera gate, fullscreen, timer, ML monitoring */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import {
  getExam,
  isEnrolled,
  getStudentExamSession,
  assignQuestionsToStudent,
  saveAnswer,
  submitExam,
} from "../api/examApi";
import useProctoring from "../hooks/useProctoring.js";
import QuizQuestion from "../components/QuizQuestion.jsx";
import Timer from "../components/Timer.jsx";
import { GraduationCap, FileText, CheckCircle, AlertTriangle, Camera as CameraIcon } from "lucide-react";

const LETTERS = ["A", "B", "C", "D"];

/** <video> that mirrors the single shared camera stream (no second getUserMedia). */
function CameraPreview({ stream, className }) {
  const ref = useCallback((el) => {
    if (el && stream && el.srcObject !== stream) {
      el.srcObject = stream;
      el.play().catch(() => {});
    }
  }, [stream]);
  return <video ref={ref} className={className} autoPlay muted playsInline />;
}

export default function ExamRoom() {
  const { examId } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();

  const [phase, setPhase]   = useState("loading"); // loading | blocked | gate | exam | submitted
  const [blockMsg, setBlockMsg] = useState("");
  const [exam, setExam]     = useState(null);
  const [resuming, setResuming] = useState(false);  // true when this student already started the exam
  const [questions, setQuestions] = useState([]);
  const [answers, setAnswers]     = useState({});   // { questionId: "A".."D" }
  const [qIndex, setQIndex] = useState(0);
  const [endsAt, setEndsAt] = useState(0);
  const [starting, setStarting] = useState(false);
  const [gateError, setGateError] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitting, setSubmitting]   = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(true);

  const saveChain    = useRef(Promise.resolve()); // serialises answer writes
  const submittedRef = useRef(false);

  const proctor = useProctoring({ uid: user?.uid, examId });
  const { camera, cameraError, stream, monitor, calibrating, calibProgress } = proctor;

  /* ── Pre-flight checks (unchanged rules) ───────────────── */
  useEffect(() => {
    if (!user) return;
    (async () => {
      try {
        const ex = await getExam(examId);
        if (!ex) { setBlockMsg("This exam does not exist."); return setPhase("blocked"); }
        setExam(ex);

        const session = await getStudentExamSession(examId, user.uid);
        if (session?.submitted) {
          setBlockMsg("You have already submitted this exam.");
          return setPhase("blocked");
        }
        if (!(await isEnrolled(ex.course_id, user.uid))) {
          setBlockMsg("You are not enrolled in this course.");
          return setPhase("blocked");
        }
        if (!ex.is_live && !session) {
          setBlockMsg("This exam is not live.");
          return setPhase("blocked");
        }
        setResuming(!!session);
        setPhase("gate");
      } catch (err) {
        setBlockMsg(`Could not load exam: ${err.message}`);
        setPhase("blocked");
      }
    })();
  }, [examId, user]);

  /* ── Leaving the page: release fullscreen (camera + socket are released by the hook) ── */
  useEffect(() => () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }, []);

  /* ── Fullscreen tracking ───────────────────────────────── */
  useEffect(() => {
    if (phase !== "exam") return;
    const onChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [phase]);

  /* ── Start / resume ────────────────────────────────────── */
  async function handleStart() {
    setGateError("");
    setStarting(true);
    try {
      if (camera !== "ready") throw new Error("Enable your camera before starting.");

      try {
        await document.documentElement.requestFullscreen();
      } catch {
        throw new Error("Fullscreen is required for this exam. Please allow it and try again.");
      }

      const qs = await assignQuestionsToStudent(examId, user.uid, exam.pick_n);
      if (qs.length === 0) throw new Error("This exam has no questions.");
      const session = await getStudentExamSession(examId, user.uid);
      const startedMs = session.started_at?.toMillis?.() ?? Date.now();

      setQuestions(qs);
      setAnswers(session.answers || {});
      setEndsAt(startedMs + exam.duration_sec * 1000);

      proctor.startMonitoring();       // opens /ws/student/{uid}?exam_id=... and starts frames
      setPhase("exam");
    } catch (err) {
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
      setGateError(err.message);
    } finally {
      setStarting(false);
    }
  }

  /* ── Answering ─────────────────────────────────────────── */
  function handleSelect(qId, optIndex) {
    const letter = LETTERS[optIndex];
    setAnswers(prev => ({ ...prev, [qId]: letter }));
    saveChain.current = saveChain.current
      .then(() => saveAnswer(examId, user.uid, qId, letter))
      .catch(err => console.error("saveAnswer failed:", err));
  }

  /* ── Submit (manual or timer) ──────────────────────────── */
  const handleSubmit = useCallback(async () => {
    if (submittedRef.current) return;
    submittedRef.current = true;
    setSubmitting(true);
    setConfirmOpen(false);
    try {
      await saveChain.current;                 // flush pending answers
      await submitExam(examId, user.uid);
      proctor.stop();                          // closes the WebSocket, stops the camera
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
      setPhase("submitted");
    } catch (err) {
      submittedRef.current = false;            // allow retry
      alert(`Submit failed: ${err.message}. Please try again.`);
    } finally {
      setSubmitting(false);
    }
  }, [examId, user, proctor]);

  /* ── Render ────────────────────────────────────────────── */
  if (phase === "loading") return <div className="loading-spinner">Loading exam...</div>;

  if (phase === "blocked") {
    return (
      <div className="room-center">
        <div className="card room-card">
          <div className="room-emoji"><AlertTriangle size={64} color="#ef4444" strokeWidth={1.5} /></div>
          <h1>Cannot start exam</h1>
          <p>{blockMsg}</p>
          <button className="btn btn-primary" onClick={() => navigate("/student/dashboard")}>
            Back to Dashboard
          </button>
        </div>
      </div>
    );
  }

  if (phase === "submitted") {
    return (
      <div className="room-center">
        <div className="card room-card">
          <div className="room-emoji"><CheckCircle size={64} color="#10b981" strokeWidth={1.5} /></div>
          <h1>Exam Submitted</h1>
          <p>Your answers have been recorded.</p>
          <div style={{ display: "flex", gap: "16px", justifyContent: "center" }}>
            <button className="btn btn-primary" onClick={() => navigate(`/results/${examId}`)}>
              View Results
            </button>
            <button className="btn btn-ghost" onClick={() => navigate("/student/dashboard")}>
              Back to Dashboard
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (phase === "gate") {
    const cameraReady = camera === "ready";
    return (
      <div className="room-center">
        <div className="card room-card">
          <div className="room-emoji"><GraduationCap size={56} color="#0ea5e9" strokeWidth={1.5} /></div>
          <h1>{exam.title}</h1>
          <p>This exam is proctored. Make sure your face is clearly visible in a well-lit room.</p>

          {resuming && (
            <div className="alert success" style={{ width: "100%", textAlign: "left" }}>
              You already started this exam. Your questions, answers and remaining time are saved —
              enable your camera to resume.
            </div>
          )}

          <ul className="room-rules">
            <li>✓ {Math.min(exam.pick_n, exam.total_q)} multiple-choice questions</li>
            <li>✓ {Math.floor(exam.duration_sec / 60)} minute time limit; auto-submits at zero</li>
            <li>✓ Webcam must stay on for the whole exam</li>
            <li>✓ The exam runs in fullscreen — leaving it is flagged</li>
            <li>✓ Behaviour monitoring is active</li>
          </ul>

          {/* Step 1 — camera permission + preview */}
          <div className="gate-camera">
            {cameraReady
              ? <CameraPreview stream={stream} className="gate-preview" />
              : <div className="gate-preview gate-preview-empty">Camera is off</div>}
          </div>
          {cameraError && <div className="alert error">{cameraError}</div>}
          {!cameraReady && (
            <button
              className="btn btn-primary room-start"
              onClick={proctor.requestCamera}
              disabled={camera === "requesting"}
            >
              {camera === "requesting" ? "Waiting for permission..." : <><CameraIcon size={20} style={{marginRight: "8px"}} /> Enable Camera</>}
            </button>
          )}
          {cameraReady && (
            <p className="gate-ok">✓ Camera working. Check that your face is centred and well lit.</p>
          )}

          {/* Step 2 — fullscreen + start (needs the camera) */}
          {gateError && <div className="alert error">{gateError}</div>}
          <button
            className="btn btn-primary room-start"
            onClick={handleStart}
            disabled={!cameraReady || starting}
          >
            {starting ? "Starting..." : resuming ? "Resume Exam (fullscreen)" : "Start Exam (fullscreen)"}
          </button>
          <button className="back-link" onClick={() => { proctor.stop(); navigate("/student/dashboard"); }}>
            Cancel
          </button>
        </div>
      </div>
    );
  }

  // phase === "exam"
  const q = questions[qIndex];
  const qView = q && {
    question: q.question,
    options: [q.opt_a, q.opt_b, q.opt_c, q.opt_d],
  };
  const answeredCount = Object.keys(answers).length;
  const cameraLost = camera === "lost" || camera === "error" || camera === "denied";

  return (
    <div className="room-root">
      <header className="room-header">
        <span className="room-title" style={{ display: "flex", alignItems: "center", gap: "8px" }}><FileText size={20} /> {exam.title}</span>
        <div className="room-header-right">
          {/* Connection state only — never the score or any warning */}
          <span className={`badge ${monitor === "live" ? "badge-ok" : "badge-warn"}`}>
            {monitor === "live" ? "CAMERA ON"
              : monitor === "unavailable" ? "MONITORING UNAVAILABLE"
              : "CONNECTING"}
          </span>
          <Timer endsAt={endsAt} onExpire={handleSubmit} />
        </div>
      </header>

      {monitor === "live" && calibrating && (
        <div className="alert success calib-banner">
          Calibrating — please look straight at the screen and stay still ({Math.round(calibProgress * 100)}%)
        </div>
      )}
      {monitor === "unavailable" && (
        <div className="alert error calib-banner">
          Live monitoring could not connect. You can keep working; keep your camera on and your face visible.
        </div>
      )}

      <div className="room-body">
        <div className="room-main">
          <QuizQuestion
            question={qView}
            qIndex={qIndex}
            total={questions.length}
            selectedIndex={answers[q.id] ? LETTERS.indexOf(answers[q.id]) : null}
            onSelect={(i) => handleSelect(q.id, i)}
            submitted={submitting}
          />

          <div className="room-footer">
            <button className="nav-btn" onClick={() => setQIndex(i => Math.max(0, i - 1))} disabled={qIndex === 0}>
              ← Previous
            </button>
            <div className="q-dots">
              {questions.map((qq, i) => (
                <button
                  key={qq.id}
                  onClick={() => setQIndex(i)}
                  className={`q-dot ${i === qIndex ? "active" : ""} ${answers[qq.id] ? "answered" : ""}`}
                >
                  {i + 1}
                </button>
              ))}
            </div>
            {qIndex < questions.length - 1 ? (
              <button className="nav-btn" onClick={() => setQIndex(i => i + 1)}>Next →</button>
            ) : (
              <button className="nav-btn" onClick={() => setConfirmOpen(true)}>Submit ✓</button>
            )}
          </div>
        </div>

        <aside className="room-side">
          <div className="camera-box">
            <CameraPreview stream={stream} />
          </div>
          <div className="exam-progress-card">
            <p className="answered-text">{answeredCount} / {questions.length} answered</p>
            <button className="btn btn-primary submit-exam-btn" onClick={() => setConfirmOpen(true)} disabled={submitting}>
              Submit Exam
            </button>
          </div>
        </aside>
      </div>

      {confirmOpen && (
        <div className="modal-overlay">
          <div className="modal">
            <h2>Submit exam?</h2>
            <p style={{ color: "var(--text-secondary)" }}>
              You have answered {answeredCount} of {questions.length} questions.
              {answeredCount < questions.length && " Unanswered questions will be marked wrong."}
              {" "}This cannot be undone.
            </p>
            <div className="modal-actions">
              <button className="modal-cancel" onClick={() => setConfirmOpen(false)}>Keep working</button>
              <button className="action-btn" onClick={handleSubmit} disabled={submitting}>
                {submitting ? "Submitting..." : "Submit"}
              </button>
            </div>
          </div>
        </div>
      )}

      {cameraLost && !submitting && (
        <div className="modal-overlay" style={{ zIndex: 210 }}>
          <div className="modal">
            <h2>📷 Camera problem</h2>
            <p style={{ color: "var(--text-secondary)" }}>
              {cameraError || "Your camera stopped."} Reconnect it to continue. The timer is still running.
            </p>
            <div className="modal-actions">
              <button className="modal-cancel" onClick={() => setConfirmOpen(true)}>Submit now</button>
              <button className="action-btn" onClick={proctor.requestCamera}>Reconnect camera</button>
            </div>
          </div>
        </div>
      )}

      {!isFullscreen && !submitting && (
        <div className="modal-overlay" style={{ zIndex: 200 }}>
          <div className="modal">
            <h2>⚠ Fullscreen required</h2>
            <p style={{ color: "var(--text-secondary)" }}>
              You left fullscreen mode. Return to fullscreen to continue — the timer is still running.
            </p>
            <div className="modal-actions">
              <button
                className="action-btn"
                onClick={() => document.documentElement.requestFullscreen().catch(() => {})}
              >
                Return to Fullscreen
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
