// src/pages/StudentExam.jsx
// Student-facing: quiz + timer + camera preview + WebSocket monitor link.
import React, { useEffect, useRef, useState, useCallback } from "react";
import QuizQuestion from "../components/QuizQuestion.jsx";
import MonitoringStatus from "../components/MonitoringStatus.jsx";
import { openSocket, sendJSON } from "../api/websocket.js";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function StudentExam({ studentId = "s001" }) {
  // Quiz state
  const [questions, setQuestions] = useState([]);
  const [duration, setDuration]   = useState(1800);
  const [timeLeft, setTimeLeft]   = useState(null);
  const [qIndex, setQIndex]       = useState(0);
  const [answers, setAnswers]     = useState({});
  const [submitted, setSubmitted] = useState(false);
  const [examStarted, setExamStarted] = useState(false);

  // Monitoring state
  const [monitorStatus, setMonitorStatus] = useState(null);
  const [wsConnected, setWsConnected]     = useState(false);

  // Refs
  const videoRef    = useRef(null);
  const visibleVideoRef = useRef(null);  // the on-screen mirror preview
  const canvasRef   = useRef(null);
  const wsRef       = useRef(null);
  const captureRef  = useRef(null);
  const streamRef   = useRef(null);

  // ── Fetch quiz on mount ─────────────────────────────────────────
  useEffect(() => {
    fetch(`${API_BASE}/api/quiz`)
      .then(r => r.json())
      .then(data => {
        setQuestions(data.questions);
        setDuration(data.duration_seconds);
        setTimeLeft(data.duration_seconds);
      })
      .catch(err => console.error("Failed to fetch quiz:", err));
  }, []);

  // ── Timer ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!examStarted || submitted) return;
    const id = setInterval(() => {
      setTimeLeft(t => {
        if (t <= 1) { clearInterval(id); handleSubmit(); return 0; }
        return t - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [examStarted, submitted]);

  // ── Format time ─────────────────────────────────────────────────
  const fmt = (s) => {
    const m = Math.floor(s / 60).toString().padStart(2, "0");
    const sec = (s % 60).toString().padStart(2, "0");
    return `${m}:${sec}`;
  };

  // ── Start exam: open camera + WebSocket ─────────────────────────
  const handleStart = useCallback(async () => {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
        audio: false,
      });
    } catch (e) {
      alert(`Camera access is required for this exam.\n\nError: ${e.message}`);
      return;
    }

    streamRef.current = stream;

    // Attach stream and wait for video to be ready before doing anything else
    await new Promise((resolve) => {
      const video = videoRef.current;
      video.srcObject = stream;
      video.onloadedmetadata = () => {
        video.play()
          .then(resolve)
          .catch((err) => {
            console.warn("video.play() failed:", err);
            resolve(); // continue anyway
          });
      };
    });

    // Open student WebSocket
    wsRef.current = openSocket(
      `/ws/student/${studentId}`,
      (msg) => {
        if (msg.type === "status") setMonitorStatus(msg);
      },
      () => setWsConnected(true),
      () => setWsConnected(false),
    );

    // Start frame capture loop at ~2 FPS
    // Video is guaranteed to have dimensions now
    captureRef.current = setInterval(() => {
      const video  = videoRef.current;
      const canvas = canvasRef.current;
      const ws     = wsRef.current;
      if (!video || !canvas || !ws) return;
      if (video.readyState < 2) return;  // HAVE_CURRENT_DATA not yet available
      canvas.width  = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      const b64 = canvas.toDataURL("image/jpeg", 0.7);
      sendJSON(ws, { type: "frame", data: b64 });
    }, 500);

    setExamStarted(true);
  }, [studentId]);

  // ── Cleanup on unmount ──────────────────────────────────────────
  useEffect(() => {
    return () => {
      clearInterval(captureRef.current);
      wsRef.current?.close();
      streamRef.current?.getTracks().forEach(t => t.stop());
    };
  }, []);

  // Mirror stream to the visible preview once exam starts
  useEffect(() => {
    if (examStarted && visibleVideoRef.current && streamRef.current) {
      visibleVideoRef.current.srcObject = streamRef.current;
      visibleVideoRef.current.play().catch(() => {});
    }
  }, [examStarted]);

  // ── Submit exam ─────────────────────────────────────────────────
  const handleSubmit = useCallback(() => {
    setSubmitted(true);
    clearInterval(captureRef.current);
    wsRef.current?.close();
    streamRef.current?.getTracks().forEach(t => t.stop());
  }, []);

  const scoreColor = monitorStatus
    ? monitorStatus.score >= 80 ? "var(--ok)"
    : monitorStatus.score >= 50 ? "var(--warn)"
    : "var(--danger)"
    : "var(--text-secondary)";

  const timerColor = timeLeft !== null && timeLeft < 300 ? "var(--danger)" : "var(--text-primary)";

  // Always-mounted hidden video+canvas so videoRef is never null in handleStart
  const alwaysVideo = (
    <div style={{ position: "fixed", width: 0, height: 0, overflow: "hidden", opacity: 0, pointerEvents: "none" }}>
      <video ref={videoRef} autoPlay muted playsInline />
      <canvas ref={canvasRef} />
    </div>
  );

  if (!examStarted) {
    return (
      <>
        {alwaysVideo}
        <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: "24px" }}>
          <div className="card fade-in" style={{ maxWidth: "500px", width: "100%", padding: "48px 40px", textAlign: "center" }}>
            <div style={{ fontSize: "3rem", marginBottom: "16px" }}>🎓</div>
            <h1 style={{ fontSize: "1.6rem", fontWeight: 700, marginBottom: "8px" }}>Online Exam</h1>
            <p style={{ color: "var(--text-secondary)", marginBottom: "32px", lineHeight: 1.6 }}>
              This exam will monitor your behaviour via webcam.
              Please ensure your face is clearly visible and you are in a well-lit environment.
            </p>
            <div style={{ textAlign: "left", padding: "16px 20px", background: "var(--bg-surface)", borderRadius: "var(--radius-sm)", marginBottom: "32px" }}>
              <p style={{ fontSize: "0.8rem", color: "var(--text-secondary)", lineHeight: 1.7 }}>
                &#10003; &nbsp;{questions.length} multiple-choice questions<br/>
                &#10003; &nbsp;{Math.round(duration / 60)} minute time limit<br/>
                &#10003; &nbsp;Webcam required throughout the exam<br/>
                &#10003; &nbsp;Behaviour monitoring is active
              </p>
            </div>
            <button
              className="btn btn-primary"
              style={{ width: "100%", justifyContent: "center", fontSize: "1rem", padding: "14px" }}
              onClick={handleStart}
              disabled={questions.length === 0}
            >
              {questions.length === 0 ? "Loading..." : "Start Exam"}
            </button>
          </div>
        </div>
      </>
    );
  }

  // ── Results screen ──────────────────────────────────────────────
  if (submitted) {
    const correct = questions.filter((q, i) =>
      answers[q.id] !== undefined && answers[q.id] === questions[i]?.answer_index
    ).length;
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: "24px" }}>
        <div className="card fade-in" style={{ maxWidth: "480px", width: "100%", padding: "48px 40px", textAlign: "center" }}>
          <div style={{ fontSize: "3rem", marginBottom: "16px" }}>✅</div>
          <h1 style={{ fontSize: "1.6rem", fontWeight: 700, marginBottom: "8px" }}>Exam Submitted</h1>
          <p style={{ color: "var(--text-secondary)", marginBottom: "32px" }}>Your answers have been recorded.</p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "16px" }}>
            <div style={{ padding: "20px", background: "var(--bg-surface)", borderRadius: "var(--radius-sm)" }}>
              <p style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.06em" }}>Answered</p>
              <p style={{ fontSize: "1.8rem", fontWeight: 700, color: "var(--ok)" }}>{Object.keys(answers).length}<span style={{ fontSize: "1rem", color: "var(--text-muted)" }}>/{questions.length}</span></p>
            </div>
            <div style={{ padding: "20px", background: "var(--bg-surface)", borderRadius: "var(--radius-sm)" }}>
              <p style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.06em" }}>Monitor Score</p>
              <p style={{ fontSize: "1.8rem", fontWeight: 700, color: scoreColor }}>{monitorStatus?.score ?? 100}<span style={{ fontSize: "1rem", color: "var(--text-muted)" }}>/100</span></p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Active exam ─────────────────────────────────────────────────
  const q = questions[qIndex];
  return (
    <>
    {alwaysVideo}
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <header style={{
        position: "sticky", top: 0, zIndex: 100,
        background: "rgba(13,15,26,0.92)", backdropFilter: "blur(12px)",
        borderBottom: "1px solid var(--border)",
        padding: "12px 24px",
        display: "flex", alignItems: "center", justifyContent: "space-between"
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ fontSize: "1rem", fontWeight: 700 }}>📝 Online Exam</span>
          <span style={{ fontSize: "0.7rem", color: "var(--text-secondary)", padding: "3px 8px", background: "var(--bg-surface)", borderRadius: "4px" }}>
            {studentId}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          <span
            className={`badge ${wsConnected ? "badge-ok" : "badge-warn"}`}
            style={{ fontSize: "0.68rem" }}
          >
            <span className={`dot ${wsConnected ? "dot-ok" : "dot-warn"}`} />
            {wsConnected ? "MONITORED" : "CONNECTING"}
          </span>
          <span style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: "1.2rem",
            fontWeight: 700,
            color: timerColor,
            minWidth: "60px",
            textAlign: "right",
          }}>
            {timeLeft !== null ? fmt(timeLeft) : "--:--"}
          </span>
        </div>
      </header>

      {/* Body */}
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 280px", gap: "24px", padding: "24px", maxWidth: "1100px", margin: "0 auto", width: "100%" }}>

        {/* Left: quiz */}
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {q && (
            <QuizQuestion
              question={q}
              qIndex={qIndex}
              total={questions.length}
              selectedIndex={answers[q.id] ?? null}
              onSelect={(i) => setAnswers(prev => ({ ...prev, [q.id]: i }))}
              submitted={submitted}
            />
          )}

          {/* Navigation */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <button
              className="btn btn-ghost"
              onClick={() => setQIndex(i => Math.max(0, i - 1))}
              disabled={qIndex === 0}
            >
              ← Previous
            </button>
            <div style={{ display: "flex", gap: "8px" }}>
              {questions.map((_, i) => {
                const ans = answers[questions[i]?.id];
                return (
                  <button
                    key={i}
                    onClick={() => setQIndex(i)}
                    style={{
                      width: "32px", height: "32px", borderRadius: "50%",
                      border: `2px solid ${i === qIndex ? "var(--accent)" : ans !== undefined ? "var(--ok)" : "var(--border)"}`,
                      background: i === qIndex ? "var(--accent)" : ans !== undefined ? "var(--ok-bg)" : "transparent",
                      color: i === qIndex ? "#fff" : ans !== undefined ? "var(--ok)" : "var(--text-muted)",
                      fontSize: "0.75rem", fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                    }}
                  >
                    {i + 1}
                  </button>
                );
              })}
            </div>
            {qIndex < questions.length - 1 ? (
              <button className="btn btn-primary" onClick={() => setQIndex(i => i + 1)}>Next →</button>
            ) : (
              <button
                className="btn btn-primary"
                onClick={handleSubmit}
                style={{ background: "var(--ok)", color: "#000" }}
              >
                Submit Exam ✓
              </button>
            )}
          </div>
        </div>

        {/* Right: camera + monitoring */}
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {/* Camera preview */}
          <div className="card" style={{ overflow: "hidden", aspectRatio: "4/3", position: "relative" }}>
            <video
              ref={visibleVideoRef}
              autoPlay muted playsInline
              style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scaleX(-1)" }}
            />
            <canvas style={{ display: "none" }} />
            <div style={{
              position: "absolute", bottom: "8px", left: "8px",
              fontSize: "0.65rem", color: "rgba(255,255,255,0.7)",
              background: "rgba(0,0,0,0.5)", padding: "3px 7px", borderRadius: "4px",
            }}>
              LIVE
            </div>
          </div>

          {/* Monitoring status */}
          <MonitoringStatus status={monitorStatus} />

          {/* Score bar */}
          {monitorStatus && !monitorStatus.calibrating && (
            <div className="card" style={{ padding: "16px 20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                <span style={{ fontSize: "0.72rem", color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Integrity Score</span>
                <span style={{ fontSize: "0.8rem", fontWeight: 600, color: scoreColor }}>{monitorStatus.score}/100</span>
              </div>
              <div className="progress-bar">
                <div className="progress-fill" style={{ width: `${monitorStatus.score}%`, background: scoreColor }} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
    </>
  );
}
