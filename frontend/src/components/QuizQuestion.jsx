// src/components/QuizQuestion.jsx
import React from "react";

export default function QuizQuestion({ question, qIndex, total, selectedIndex, onSelect, submitted }) {
  if (!question) return null;
  const letters = ["A", "B", "C", "D"];

  return (
    <div className="card fade-in" style={{ padding: "28px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <span style={{ fontSize: "0.72rem", color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 600 }}>
          Question {qIndex + 1} of {total}
        </span>
        <div style={{ display: "flex", gap: "4px" }}>
          {Array.from({ length: total }).map((_, i) => (
            <div
              key={i}
              style={{
                width: "6px", height: "6px", borderRadius: "50%",
                background: i === qIndex ? "var(--accent)" : "var(--border-light)"
              }}
            />
          ))}
        </div>
      </div>

      <p style={{ fontSize: "1.05rem", fontWeight: 500, lineHeight: 1.6, marginBottom: "24px", color: "var(--text-primary)" }}>
        {question.question}
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
        {question.options.map((opt, i) => {
          const isSelected = selectedIndex === i;
          return (
            <button
              key={i}
              disabled={submitted}
              onClick={() => onSelect(i)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "14px",
                padding: "14px 18px",
                background: isSelected ? "rgba(88,101,242,0.15)" : "var(--bg-surface)",
                border: `1px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
                borderRadius: "var(--radius-sm)",
                color: isSelected ? "var(--accent-light)" : "var(--text-primary)",
                fontSize: "0.9rem",
                cursor: submitted ? "default" : "pointer",
                transition: "all 0.15s ease",
                textAlign: "left",
                fontFamily: "inherit",
              }}
              onMouseEnter={(e) => { if (!submitted && !isSelected) e.currentTarget.style.background = "var(--bg-hover)"; }}
              onMouseLeave={(e) => { if (!submitted && !isSelected) e.currentTarget.style.background = "var(--bg-surface)"; }}
            >
              <span
                style={{
                  minWidth: "28px", height: "28px",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  background: isSelected ? "var(--accent)" : "var(--border)",
                  borderRadius: "50%",
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  color: isSelected ? "#fff" : "var(--text-secondary)",
                  flexShrink: 0,
                }}
              >
                {letters[i]}
              </span>
              {opt}
            </button>
          );
        })}
      </div>
    </div>
  );
}
