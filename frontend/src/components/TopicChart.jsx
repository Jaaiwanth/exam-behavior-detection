/* src/components/TopicChart.jsx — Horizontal bars: % correct per topic */
import React from "react";

export default function TopicChart({ topicScores }) {
  const rows = Object.entries(topicScores || {})
    .map(([topic, { correct, total }]) => ({
      topic, correct, total, pct: total ? Math.round((correct / total) * 100) : 0,
    }))
    .sort((a, b) => a.pct - b.pct); // weakest first

  if (rows.length === 0) return <p className="detail-hint">No topic data.</p>;

  return (
    <div className="topic-chart">
      {rows.map(r => (
        <div key={r.topic} className="topic-row">
          <div className="topic-label">
            <span>{r.topic}</span>
            <span className="topic-count">{r.correct}/{r.total} · {r.pct}%</span>
          </div>
          <div className="topic-track">
            <div
              className="topic-fill"
              style={{
                width: `${r.pct}%`,
                background: r.pct >= 70 ? "var(--ok)" : r.pct >= 40 ? "var(--warn)" : "var(--danger)",
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
