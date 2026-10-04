/* src/components/ResultsView.jsx — Gauge, topic bars, trend and answer review for one result.
   Shared by the student Results page and the mentor's per-student view. */
import React from "react";
import ScoreGauge from "./ScoreGauge.jsx";
import TopicChart from "./TopicChart.jsx";
import TrendChart from "./TrendChart.jsx";

const LETTERS = ["A", "B", "C", "D"];

export default function ResultsView({ bundle }) {
  const { result, review, trend, rank, participants } = bundle;
  const wrong = result.total - result.score;

  return (
    <div className="detail-grid">
      {/* 1. Overall score gauge */}
      <section className="detail-card results-gauge">
        <h2>Overall Score</h2>
        <ScoreGauge percentage={result.percentage} />
        <div className="results-stats">
          <div><strong>{result.score}</strong><span>Correct</span></div>
          <div><strong>{wrong}</strong><span>Wrong / skipped</span></div>
          {rank && <div><strong>#{rank}</strong><span>of {participants}</span></div>}
        </div>
      </section>

      {/* 2. Topic bars */}
      <section className="detail-card">
        <h2>Topic-wise Performance</h2>
        <p className="detail-hint">Weakest topics first</p>
        <TopicChart topicScores={result.topic_scores} />
      </section>

      {/* 3. Trend */}
      <section className="detail-card full-width">
        <h2>Performance Trend</h2>
        <TrendChart points={trend} />
      </section>

      {/* 4. Answer review */}
      <section className="detail-card full-width">
        <h2>Answer Review</h2>
        <div className="review-list">
          {review.map((q, i) => {
            const ok = q.given === q.correct;
            const opts = { A: q.opt_a, B: q.opt_b, C: q.opt_c, D: q.opt_d };
            return (
              <div key={q.id} className={`review-item ${ok ? "ok" : "bad"}`}>
                <div className="review-head">
                  <span className="q-num">{i + 1}</span>
                  <span className="review-q">{q.question}</span>
                  <span className={`badge ${ok ? "badge-ok" : "badge-danger"}`}>
                    {ok ? "Correct" : q.given ? "Wrong" : "Skipped"}
                  </span>
                </div>
                <div className="review-opts">
                  {LETTERS.map(l => (
                    <div
                      key={l}
                      className={`review-opt ${l === q.correct ? "is-correct" : ""} ${l === q.given && !ok ? "is-wrong" : ""}`}
                    >
                      <b>{l}</b> {opts[l]}
                      {l === q.correct && <span className="review-tag">correct answer</span>}
                      {l === q.given && !ok && <span className="review-tag">their answer</span>}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
