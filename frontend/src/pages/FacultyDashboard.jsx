// src/pages/FacultyDashboard.jsx
// Faculty-facing: live camera feed, behaviour events, score, flags.
import React, { useEffect, useRef, useState } from "react";
import MonitoringStatus from "../components/MonitoringStatus.jsx";
import { openSocket, sendJSON } from "../api/websocket.js";
import { auth } from "../firebase";
import { GraduationCap } from "lucide-react";

export default function FacultyDashboard({ studentId = "s001" }) {
  const [analysis, setAnalysis]     = useState(null);
  const [eventLog, setEventLog]     = useState([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [hasFrames, setHasFrames]   = useState(false);  // true once first frame arrives
  const imgRef = useRef(null);
  const wsRef  = useRef(null);

  useEffect(() => {
    wsRef.current = openSocket(
      `/ws/faculty/${studentId}`,
      (msg) => {
        if (msg.type !== "analysis") return;
        setAnalysis(msg);

        // Update camera preview image
        if (msg.frame_b64) {
          setHasFrames(true);
          if (imgRef.current) {
            const src = msg.frame_b64.startsWith("data:")
              ? msg.frame_b64
              : `data:image/jpeg;base64,${msg.frame_b64}`;
            imgRef.current.src = src;
          }
        }

        // Append to event log only when a new warning fires
        if (msg.new_warning) {
          setEventLog(prev => [{
            id: Date.now(),
            time: new Date().toLocaleTimeString(),
            reason: msg.new_warning,
            score: msg.score,
          }, ...prev].slice(0, 50)); // keep last 50 events
        }
      },
      async () => {
        // The backend only streams live video / scores to authenticated staff.
        const token = await auth.currentUser?.getIdToken();
        if (token) sendJSON(wsRef.current, { type: "auth", token });
        setWsConnected(true);
      },
      () => setWsConnected(false),
    );
    return () => wsRef.current?.close();
  }, [studentId]);

  const scoreColor = analysis
    ? analysis.score >= 80 ? "var(--ok)"
    : analysis.score >= 50 ? "var(--warn)"
    : "var(--danger)"
    : "var(--text-secondary)";

  const flags = analysis?.flags || {};
  const flagItems = [
    { key: "head_turned_left",  label: "Head Left" },
    { key: "head_turned_right", label: "Head Right" },
    { key: "face_absent",       label: "Face Absent" },
    { key: "identity_mismatch", label: "ID Mismatch" },
    { key: "phone_visible",     label: "Phone" },
    { key: "laptop_visible",    label: "Laptop" },
    { key: "person_visible",    label: "Extra Person" },
    { key: "book_visible",      label: "Book" },
    { key: "hand_near_face",    label: "Hand Near Face" },
  ];

  const timers = analysis?.timers || {};

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <header style={{
        position: "sticky", top: 0, zIndex: 100,
        background: "rgba(13,15,26,0.92)", backdropFilter: "blur(12px)",
        borderBottom: "1px solid var(--border)",
        padding: "12px 24px",
        display: "flex", alignItems: "center", justifyContent: "space-between"
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span style={{ fontSize: "1rem", fontWeight: 700, display: "flex", alignItems: "center", gap: "8px" }}><GraduationCap size={20} color="#0ea5e9" /> Faculty Dashboard</span>
          <span style={{ fontSize: "0.7rem", color: "var(--text-secondary)", padding: "3px 8px", background: "var(--bg-surface)", borderRadius: "4px" }}>
            Watching: {studentId}
          </span>
        </div>
        <span className={`badge ${wsConnected ? "badge-ok" : "badge-warn"}`}>
          <span className={`dot ${wsConnected ? "dot-ok" : "dot-warn"}`} />
          {wsConnected ? "LIVE" : "DISCONNECTED"}
        </span>
      </header>

      {/* Main grid */}
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 340px", gap: "20px", padding: "20px", maxWidth: "1200px", margin: "0 auto", width: "100%" }}>

        {/* Left column */}
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>

          {/* Camera feed */}
          <div className="card" style={{ overflow: "hidden" }}>
            <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Student Camera</span>
              {hasFrames && <span className="badge badge-danger" style={{ fontSize: "0.68rem", animation: "warning-flash 2s ease infinite" }}>● REC</span>}
            </div>
            <div style={{ aspectRatio: "16/9", background: "#0a0b12", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
              {/* img is always mounted so imgRef is valid; hidden until first frame */}
              <img
                ref={imgRef}
                alt="Student camera feed"
                style={{ width: "100%", height: "100%", objectFit: "contain", display: hasFrames ? "block" : "none" }}
              />
              {/* Overlay: show when no frame received yet */}
              {!hasFrames && (
                <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "12px" }}>
                  <div style={{ fontSize: "2.5rem" }}>📷</div>
                  <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                    {wsConnected ? "Waiting for student to start exam..." : "Disconnected — reconnecting..."}
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Behaviour flags grid */}
          <div className="card" style={{ padding: "16px 20px" }}>
            <p style={{ fontSize: "0.72rem", fontWeight: 700, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "14px" }}>
              Detection Flags
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "10px" }}>
              {flagItems.map(({ key, label }) => {
                const active = !!flags[key];
                return (
                  <div key={key} style={{
                    padding: "10px 12px",
                    background: active ? (key === "hand_near_face" ? "rgba(251,191,36,0.1)" : "var(--danger-bg)") : "var(--bg-surface)",
                    border: `1px solid ${active ? (key === "hand_near_face" ? "rgba(251,191,36,0.3)" : "rgba(239,68,68,0.3)") : "var(--border)"}`,
                    borderRadius: "var(--radius-sm)",
                    transition: "all 0.2s ease",
                  }}>
                    <p style={{ fontSize: "0.65rem", color: "var(--text-muted)", marginBottom: "4px", textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</p>
                    <span className={`badge ${active ? (key === "hand_near_face" ? "badge-warn" : "badge-danger") : "badge-muted"}`} style={{ fontSize: "0.65rem" }}>
                      {active ? "ACTIVE" : "CLEAR"}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Timer bars */}
          {analysis && !analysis.calibrating && (
            <div className="card" style={{ padding: "16px 20px" }}>
              <p style={{ fontSize: "0.72rem", fontWeight: 700, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "14px" }}>
                Violation Timers
              </p>
              {[
                { label: "Head Turn", val: timers.head_sus_secs || 0, max: 10 },
                { label: "Face Absent", val: timers.absent_secs || 0, max: 5 },
                { label: "ID Mismatch", val: timers.id_sus_secs || 0, max: 4 },
                { label: "Phone", val: timers.yolo_elapsed?.phone || 0, max: 3 },
                { label: "Laptop", val: timers.yolo_elapsed?.laptop || 0, max: 3 },
                { label: "Extra Person", val: timers.yolo_elapsed?.person || 0, max: 5 },
                { label: "Book", val: timers.yolo_elapsed?.book || 0, max: 8 },
              ].map(({ label, val, max }) => {
                const pct = Math.min(val / max, 1);
                const col = pct < 0.5 ? "var(--ok)" : pct < 0.8 ? "var(--warn)" : "var(--danger)";
                if (val < 0.05) return null;
                return (
                  <div key={label} style={{ marginBottom: "12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "5px" }}>
                      <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>{label}</span>
                      <span style={{ fontSize: "0.72rem", fontFamily: "'JetBrains Mono', monospace", color: col }}>{val.toFixed(1)}s / {max}s</span>
                    </div>
                    <div className="progress-bar">
                      <div className="progress-fill" style={{ width: `${pct * 100}%`, background: col }} />
                    </div>
                  </div>
                );
              })}
              {[timers.head_sus_secs, timers.absent_secs, timers.id_sus_secs, ...(Object.values(timers.yolo_elapsed || {}))].every(v => !v || v < 0.05) && (
                <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>No active violations.</p>
              )}
            </div>
          )}
        </div>

        {/* Right column */}
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          {/* Score card */}
          <div className="card" style={{ padding: "24px" }}>
            <p style={{ fontSize: "0.72rem", fontWeight: 700, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "16px" }}>
              Session Status
            </p>
            {analysis ? (
              <>
                <div style={{ textAlign: "center", marginBottom: "20px" }}>
                  <p style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginBottom: "8px", textTransform: "uppercase", letterSpacing: "0.06em" }}>Integrity Score</p>
                  <p style={{ fontSize: "3rem", fontWeight: 800, color: scoreColor, fontFamily: "'JetBrains Mono', monospace", lineHeight: 1 }}>
                    {analysis.score}
                  </p>
                  <p style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>out of 100</p>
                </div>
                <div className="progress-bar" style={{ marginBottom: "20px" }}>
                  <div className="progress-fill" style={{ width: `${analysis.score}%`, background: scoreColor }} />
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                  <div style={{ padding: "12px", background: "var(--bg-surface)", borderRadius: "var(--radius-sm)", textAlign: "center" }}>
                    <p style={{ fontSize: "0.65rem", color: "var(--text-muted)", marginBottom: "4px", textTransform: "uppercase" }}>Warnings</p>
                    <p style={{ fontSize: "1.4rem", fontWeight: 700, color: analysis.warnings > 0 ? "var(--danger)" : "var(--text-secondary)" }}>
                      {analysis.warnings}
                    </p>
                  </div>
                  <div style={{ padding: "12px", background: "var(--bg-surface)", borderRadius: "var(--radius-sm)", textAlign: "center" }}>
                    <p style={{ fontSize: "0.65rem", color: "var(--text-muted)", marginBottom: "4px", textTransform: "uppercase" }}>Status</p>
                    <p style={{ fontSize: "0.8rem", fontWeight: 600, color: analysis.calibrating ? "var(--accent)" : analysis.new_warning ? "var(--danger)" : "var(--ok)" }}>
                      {analysis.calibrating ? "CALIB" : analysis.new_warning ? "ALERT" : "CLEAR"}
                    </p>
                  </div>
                </div>
              </>
            ) : (
              <div style={{ textAlign: "center", padding: "32px 0", color: "var(--text-muted)" }}>
                <div style={{ fontSize: "2rem", marginBottom: "8px" }}>⏳</div>
                <p style={{ fontSize: "0.85rem" }}>Waiting for student...</p>
              </div>
            )}
          </div>

          {/* Monitoring status badge */}
          {analysis && <MonitoringStatus status={analysis} />}

          {/* Event log */}
          <div className="card" style={{ padding: "16px 20px", flex: 1 }}>
            <p style={{ fontSize: "0.72rem", fontWeight: 700, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "14px" }}>
              Behaviour Events
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "320px", overflowY: "auto" }}>
              {eventLog.length === 0 ? (
                <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>No events yet.</p>
              ) : (
                eventLog.map(ev => (
                  <div key={ev.id} className="slide-in" style={{
                    padding: "10px 12px",
                    background: "var(--danger-bg)",
                    border: "1px solid rgba(239,68,68,0.2)",
                    borderRadius: "var(--radius-sm)",
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                      <span style={{ fontSize: "0.65rem", color: "var(--danger)", fontWeight: 600, textTransform: "uppercase" }}>WARNING</span>
                      <span style={{ fontSize: "0.65rem", color: "var(--text-muted)", fontFamily: "'JetBrains Mono', monospace" }}>{ev.time}</span>
                    </div>
                    <p style={{ fontSize: "0.78rem", color: "var(--text-primary)" }}>{ev.reason}</p>
                    <p style={{ fontSize: "0.68rem", color: "var(--text-muted)", marginTop: "2px" }}>Score → {ev.score}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
