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
import { openSocket, sendJSON } from "../api/websocket.js";
import QuizQuestion from "../components/QuizQuestion.jsx";
import Timer from "../components/Timer.jsx";

const LETTERS = ["A", "B", "C", "D"];

export default function ExamRoom() {
  const { examId } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();

  const [phase, setPhase]   = useState("loading"); // loading | blocked | gate | exam | submitted
  const [blockMsg, setBlockMsg] = useState("");
  const [exam, setExam]     = useState(null);
  const [questions, setQuestions] = useState([]);
  const [answers, setAnswers]     = useState({});   // { questionId: "A".."D" }
  const [qIndex, setQIndex] = useState(0);
  const [endsAt, setEndsAt] = useState(0);
  const [starting, setStarting] = useState(false);
  const [gateError, setGateError] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitting, setSubmitting]   = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(true);
  const [wsConnected, setWsConnected] = useState(false);

  const videoRef        = useRef(null); // hidden capture video
  const visibleVideoRef = useRef(null);
  const canvasRef       = useRef(null);
  const wsRef           = useRef(null);
  const captureRef      = useRef(null);
  const streamRef       = useRef(null);
  const saveChain       = useRef(Promise.resolve()); // serialises answer writes
  const submittedRef    = useRef(false);

  /* ── Pre-flight checks ─────────────────────────────────── */
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
        setPhase("gate");
      } catch (err) {
        setBlockMsg(`Could not load exam: ${err.message}`);
        setPhase("blocked");
      }
    })();
  }, [examId, user]);

  /* ── Teardown ──────────────────────────────────────────── */
  const stopMonitoring = useCallback(() => {
    clearInterval(captureRef.current);
    wsRef.current?.close();
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => () => {
    stopMonitoring();
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }, [stopMonitoring]);

  /* ── Fullscreen tracking ───────────────────────────────── */
  useEffect(() => {
    if (phase !== "exam") return;
    const onChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [phase]);

  /* ── Mirror stream into visible preview ────────────────── */
  useEffect(() => {
    if (phase === "exam" && visibleVideoRef.current && streamRef.current) {
      visibleVideoRef.current.srcObject = streamRef.current;
      visibleVideoRef.current.play().catch(() => {});
    }
  }, [phase]);

  /* ── Start: camera → fullscreen → questions → monitoring ─ */
  async function handleStart() {
    setGateError("");
    setStarting(true);
    try {
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
          audio: false,
        });
      } catch (e) {
        throw new Error(`Camera access is required for this exam (${e.message}).`);
      }
      streamRef.current = stream;

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

      await new Promise((resolve) => {
        const video = videoRef.current;
        video.srcObject = stream;
        video.onloadedmetadata = () => video.play().then(resolve).catch(resolve);
      });

      wsRef.current = openSocket(
        `/ws/student/${user.uid}?exam_id=${encodeURIComponent(examId)}`,
        () => {},               // status messages are intentionally hidden from the student
        () => setWsConnected(true),
        () => setWsConnected(false),
      );
      captureRef.current = setInterval(() => {
        const video = videoRef.current, canvas = canvasRef.current, ws = wsRef.current;
        if (!video || !canvas || !ws || video.readyState < 2) return;
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext("2d").drawImage(video, 0, 0);
        sendJSON(ws, { type: "frame", data: canvas.toDataURL("image/jpeg", 0.7) });
      }, 500);

      setPhase("exam");
    } catch (err) {
      stopMonitoring();
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
      stopMonitoring();
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
      setPhase("submitted");
    } catch (err) {
      submittedRef.current = false;            // allow retry
      alert(`Submit failed: ${err.message}. Please try again.`);
    } finally {
      setSubmitting(false);
    }
  }, [examId, user, stopMonitoring]);

  /* ── Render ────────────────────────────────────────────── */
  const hiddenMedia = (
    <div style={{ position: "fixed", width: 0, height: 0, overflow: "hidden", opacity: 0, pointerEvents: "none" }}>
      <video ref={videoRef} autoPlay muted playsInline />
      <canvas ref={canvasRef} />
    </div>
  );

  if (phase === "loading") return <div className="loading-spinner">Loading exam...</div>;

  if (phase === "blocked") {
    return (
      <div className="room-center">
        <div className="card room-card">
          <div className="room-emoji">🚫</div>
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
          <div className="room-emoji">✅</div>
          <h1>Exam Submitted</h1>
          <p>Your answers have been recorded.</p>
          <button className="btn btn-primary" onClick={() => navigate(`/results/${examId}`)}>
            View Results
          </button>
          <button className="back-link" onClick={() => navigate("/student/dashboard")}>
            Back to Dashboard
          </button>
        </div>
      </div>
    );
  }

  if (phase === "gate") {
    return (
      <>
        {hiddenMedia}
        <div className="room-center">
          <div className="card room-card">
            <div className="room-emoji">🎓</div>
            <h1>{exam.title}</h1>
            <p>This exam is proctored. Make sure your face is clearly visible in a well-lit room.</p>
            <ul className="room-rules">
              <li>✓ {Math.min(exam.pick_n, exam.total_q)} multiple-choice questions</li>
              <li>✓ {Math.floor(exam.duration_sec / 60)} minute time limit; auto-submits at zero</li>
              <li>✓ Webcam must stay on for the whole exam</li>
              <li>✓ The exam runs in fullscreen — leaving it is flagged</li>
              <li>✓ Behaviour monitoring is active</li>
            </ul>
            {gateError && <div className="alert error">{gateError}</div>}
            <button className="btn btn-primary room-start" onClick={handleStart} disabled={starting}>
              {starting ? "Starting..." : "Allow Camera & Start Exam"}
            </button>
            <button className="back-link" onClick={() => navigate("/student/dashboard")}>Cancel</button>
          </div>
        </div>
      </>
    );
  }

  // phase === "exam"
  const q = questions[qIndex];
  const qView = q && {
    question: q.question,
    options: [q.opt_a, q.opt_b, q.opt_c, q.opt_d],
  };
  const answeredCount = Object.keys(answers).length;

  return (
    <>
      {hiddenMedia}
      <div className="room-root">
        <header className="room-header">
          <span className="room-title">📝 {exam.title}</span>
          <div className="room-header-right">
            <span className={`badge ${wsConnected ? "badge-ok" : "badge-warn"}`}>
              {wsConnected ? "CAMERA ON" : "CONNECTING"}
            </span>
            <Timer endsAt={endsAt} onExpire={handleSubmit} />
          </div>
        </header>

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

            <div className="room-nav">
              <button className="btn btn-ghost" onClick={() => setQIndex(i => Math.max(0, i - 1))} disabled={qIndex === 0}>
                ← Previous
              </button>
              <div className="room-dots">
                {questions.map((qq, i) => (
                  <button
                    key={qq.id}
                    onClick={() => setQIndex(i)}
                    className={`room-dot ${i === qIndex ? "current" : ""} ${answers[qq.id] ? "answered" : ""}`}
                  >
                    {i + 1}
                  </button>
                ))}
              </div>
              {qIndex < questions.length - 1 ? (
                <button className="btn btn-primary" onClick={() => setQIndex(i => i + 1)}>Next →</button>
              ) : (
                <button className="btn btn-primary" onClick={() => setConfirmOpen(true)}>Submit ✓</button>
              )}
            </div>
          </div>

          <aside className="room-side">
            <div className="card room-cam">
              <video ref={visibleVideoRef} autoPlay muted playsInline />
            </div>
            <div className="card room-progress">
              <p>{answeredCount} / {questions.length} answered</p>
              <button className="btn btn-primary" onClick={() => setConfirmOpen(true)} disabled={submitting}>
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
    </>
  );
}
