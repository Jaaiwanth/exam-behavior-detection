/* src/components/TrendChart.jsx — Line chart of score % across exams (oldest to newest) */
import React from "react";

/** @param {{label: string, pct: number}[]} points oldest first */
export default function TrendChart({ points }) {
  if (points.length < 2) {
    return <p className="detail-hint">Take at least two exams to see your trend.</p>;
  }

  const W = 520, H = 200, padL = 34, padR = 14, padT = 14, padB = 28;
  const x = i => padL + (i * (W - padL - padR)) / (points.length - 1);
  const y = p => padT + ((100 - p) * (H - padT - padB)) / 100;
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.pct)}`).join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Score trend across exams">
      {[0, 50, 100].map(g => (
        <g key={g}>
          <line x1={padL} x2={W - padR} y1={y(g)} y2={y(g)} stroke="var(--border)" strokeDasharray="3 4" />
          <text x={padL - 6} y={y(g)} textAnchor="end" dominantBaseline="central" fill="var(--text-muted)" fontSize="10">
            {g}
          </text>
        </g>
      ))}
      <path d={path} fill="none" stroke="var(--accent-light)" strokeWidth="2.5" strokeLinejoin="round" />
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={x(i)} cy={y(p.pct)} r="4.5" fill="var(--accent)" stroke="var(--bg-card)" strokeWidth="2">
            <title>{`${p.label}: ${p.pct}%`}</title>
          </circle>
          {(points.length <= 8 || i === 0 || i === points.length - 1) && (
            <text x={x(i)} y={H - 8} textAnchor="middle" fill="var(--text-muted)" fontSize="10">
              {p.label.length > 10 ? p.label.slice(0, 9) + "…" : p.label}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}
