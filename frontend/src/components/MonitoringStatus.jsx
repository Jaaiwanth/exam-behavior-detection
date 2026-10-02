// src/components/MonitoringStatus.jsx
// Reusable monitoring status badge shown in student and faculty views.
import React from "react";

export default function MonitoringStatus({ status }) {
  if (!status) return null;
  const { score, warnings, calibrating, calib_progress, new_warning, active_labels } = status;

  const scoreColor =
    score >= 80 ? "var(--ok)" :
    score >= 50 ? "var(--warn)" :
    "var(--danger)";

  const overallBadge =
    calibrating       ? "badge-muted"  :
    new_warning       ? "badge-danger" :
    active_labels?.length ? "badge-warn" :
    "badge-ok";

  const overallText =
    calibrating              ? "CALIBRATING" :
    new_warning              ? "WARNING"      :
    active_labels?.length    ? "SUSPICIOUS"   :
    "CLEAR";

  return (
    <div className="monitoring-status card" style={{ padding: "16px 20px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
        <span style={{ fontSize: "0.72rem", fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-secondary)", textTransform: "uppercase" }}>
          Monitoring
        </span>
        <span className={`badge ${overallBadge}`}>
          <span className={`dot dot-${overallBadge.replace("badge-", "")}`} />
          {overallText}
        </span>
      </div>

      {calibrating ? (
        <div>
          <p style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginBottom: "8px" }}>
            Calibrating — look straight at the screen...
          </p>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${(calib_progress || 0) * 100}%`, background: "var(--accent)" }}
            />
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
          <div>
            <p style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginBottom: "4px", textTransform: "uppercase", letterSpacing: "0.06em" }}>Score</p>
            <p style={{ fontSize: "1.5rem", fontWeight: 700, color: scoreColor, fontFamily: "'JetBrains Mono', monospace" }}>
              {score}<span style={{ fontSize: "0.9rem", color: "var(--text-muted)" }}>/100</span>
            </p>
          </div>
          <div>
            <p style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginBottom: "4px", textTransform: "uppercase", letterSpacing: "0.06em" }}>Warnings</p>
            <p style={{ fontSize: "1.5rem", fontWeight: 700, color: warnings > 0 ? "var(--danger)" : "var(--text-secondary)", fontFamily: "'JetBrains Mono', monospace" }}>
              {warnings}
            </p>
          </div>
        </div>
      )}

      {new_warning && (
        <div
          style={{
            marginTop: "12px",
            padding: "10px 12px",
            background: "var(--danger-bg)",
            borderRadius: "var(--radius-sm)",
            border: "1px solid rgba(239,68,68,0.3)",
            fontSize: "0.8rem",
            color: "var(--danger)",
            animation: "warning-flash 1s ease infinite",
          }}
        >
          ⚠ {new_warning}
        </div>
      )}

      {!calibrating && active_labels?.length > 0 && (
        <div style={{ marginTop: "10px", display: "flex", flexWrap: "wrap", gap: "6px" }}>
          {active_labels.map((lbl) => (
            <span key={lbl} className="badge badge-warn" style={{ fontSize: "0.68rem" }}>
              {lbl}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
