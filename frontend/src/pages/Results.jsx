/* src/pages/Results.jsx — Student result page: gauge, topic bars, trend, answer review */
import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import {
  getResult,
  getStudentHistory,
  getStudentExamSession,
  getQuestionBank,
  getExamLeaderboard,
} from "../api/examApi";
import ScoreGauge from "../components/ScoreGauge.jsx";
import TopicChart from "../components/TopicChart.jsx";
import TrendChart from "../components/TrendChart.jsx";

const LETTERS = ["A", "B", "C", "D"];

export default function Results() {
  const { examId } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();

  const [data, setData]       = useState(null);
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const result = await getResult(examId, user.uid);
        if (!result) { setError("No result found for this exam."); return; }

        const [history, session, bank, board] = await Promise.all([
          getStudentHistory(user.uid),
          getStudentExamSession(examId, user.uid),
          getQuestionBank(examId),
          getExamLeaderboard(examId),
        ]);

        const bankMap = Object.fromEntries(bank.map(q => [q.id, q]));
        const review = (session?.question_ids || [])
          .map(id => bankMap[id])
          .filter(Boolean)
          .map(q => ({ ...q, given: session.answers?.[q.id] || null }));

        const mine = board.find(r => r.student_uid === user.uid);
        const trend = [...history].reverse().map(r => ({
          label: r.exam_title || "Exam",
          pct: r.percentage,
        }));

        setData({
          result, review, trend,
          rank: mine?.rank, participants: board.length,
        });
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [examId, user]);

  if (loading) return <div className="loading-spinner">Loading results...</div>;

  if (error || !data) {
    return (
      <div className="room-center">
        <div className="card room-card">
          <div className="room-emoji">📭</div>
          <h1>No result</h1>
          <p>{error}</p>
          <button className="btn btn-primary" onClick={() => navigate("/student/dashboard")}>
            Back to Dashboard
          </button>
        </div>
      </div>
    );
  }

  const { result, review, trend, rank, participants } = data;
  const wrong = result.total - result.score;

  return (
    <div className="dashboard-main fade-in results-page">
      <div className="page-header">
        <div>
          <button className="back-link" onClick={() => navigate("/student/dashboard")}>← Dashboard</button>
          <h1>{result.exam_title}</h1>
          <p>
            Submitted{" "}
            {result.submitted_at?.toDate ? result.submitted_at.toDate().toLocaleString() : ""}
          </p>
        </div>
        <button className="modal-cancel" onClick={() => navigate("/student/history")}>All results</button>
      </div>

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
                        {l === q.given && !ok && <span className="review-tag">your answer</span>}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
