/* src/components/ScoreGauge.jsx — Circular progress ring for an overall percentage */
import React from "react";

export default function ScoreGauge({ percentage, size = 180 }) {
  const stroke = 14;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, percentage));
  const color = pct >= 70 ? "var(--ok)" : pct >= 40 ? "var(--warn)" : "var(--danger)";

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`Overall score ${pct} percent`}
    >
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--bg-surface)" strokeWidth={stroke} />
      <circle
        cx={size / 2} cy={size / 2} r={r} fill="none"
        stroke={color} strokeWidth={stroke} strokeLinecap="round"
        strokeDasharray={circ} strokeDashoffset={circ * (1 - pct / 100)}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dashoffset .8s ease" }}
      />
      <text
        x="50%" y="50%" textAnchor="middle" dominantBaseline="central"
        fill="var(--text-primary)" fontSize={size * 0.22} fontWeight="700"
        fontFamily="'JetBrains Mono', monospace"
      >
        {pct}%
      </text>
    </svg>
  );
}
