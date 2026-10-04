/* src/components/StudentDetail.jsx — Mentor view of one student: results per exam + behaviour log */
import React, { useEffect, useState } from "react";
import { getResult, getResultBundle } from "../api/examApi";
import BehaviourReview from "./BehaviourReview.jsx";
import { getExamReviews, REVIEW_LABELS, REVIEW_BADGE } from "../api/events";
import ResultsView from "./ResultsView.jsx";

export default function StudentDetail({ course, student, exams, initialExamId, onBack }) {
  const [results, setResults]   = useState({});   // examId -> result | null
  const [examId, setExamId]     = useState(null);
  const [bundle, setBundle]     = useState(null);
  const [reviews, setReviews]   = useState({});   // examId -> review_status for this student
  const [loading, setLoading]   = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all(exams.map(async e => [e.id, await getResult(e.id, student.uid)])).then(rows => {
      if (!cancelled) setResults(Object.fromEntries(rows));
    });
    return () => { cancelled = true; };
  }, [exams, student.uid]);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled(exams.map(async e => [e.id, await getExamReviews(e.id)])).then(rows => {
      if (cancelled) return;
      const map = {};
      rows.forEach(r => {
        if (r.status !== "fulfilled") return;
        const [id, sessions] = r.value;
        const mine = sessions.find(x => x.student_id === student.uid);
        if (mine) map[id] = mine.review_status;
      });
      setReviews(map);
    });
    return () => { cancelled = true; };
  }, [exams, student.uid]);

  async function openExam(id) {
    setExamId(id);
    setBundle(null);
    setLoading(true);
    try {
      setBundle(await getResultBundle(id, student.uid, exams.map(e => e.id)));
    } catch {
      setBundle(null);
    }
    setLoading(false);
  }

  useEffect(() => {
    if (initialExamId) openExam(initialExamId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialExamId]);

  const exam = exams.find(e => e.id === examId);

  return (
    <div className="fade-in">
      <div className="page-header">
        <div>
          <button className="back-link" onClick={onBack}>← Students</button>
          <h1>{student.name}</h1>
          <p>{student.reg_no} · {student.email} · {course.name}</p>
        </div>
      </div>

      <section className="detail-card" style={{ marginBottom: 20 }}>
        <h2>Exams</h2>
        {exams.length === 0 ? (
          <p className="detail-hint">This course has no exams yet.</p>
        ) : (
          <div className="exam-list">
            {exams.map(e => {
              const r = results[e.id];
              return (
                <div
                  key={e.id}
                  className={`exam-card ${r ? "live" : "closed"}`}
                  style={{ cursor: "pointer", outline: e.id === examId ? "1px solid var(--accent)" : "none" }}
                  onClick={() => openExam(e.id)}
                >
                  <div className="exam-info">
                    <h3>{e.title}</h3>
                    <div className="exam-meta-row">
                      {r ? <span>{r.score} / {r.total} · {r.percentage}%</span> : <span>Not taken</span>}
                    </div>
                  </div>
                  {reviews[e.id] && reviews[e.id] !== "NOT_REQUIRED"
                    ? <span className={`badge ${REVIEW_BADGE[reviews[e.id]]}`}>{REVIEW_LABELS[reviews[e.id]]}</span>
                    : <span className="badge badge-muted">View</span>}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {examId && loading && <div className="loading-spinner">Loading...</div>}

      {examId && !loading && (
        <>
          <h2 className="section-title">{exam?.title}</h2>

          <BehaviourReview student={student} examId={examId} examTitle={exam?.title} />

          {bundle ? (
            <ResultsView bundle={bundle} />
          ) : (
            <div className="empty-state">
              <span>📭</span>
              <p>{student.name} has not submitted this exam.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
