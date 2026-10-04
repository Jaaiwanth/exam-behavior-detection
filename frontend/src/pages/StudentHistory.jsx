/* src/pages/StudentHistory.jsx — Past exam results */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { getStudentHistory } from "../api/examApi";

export default function StudentHistory() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");

  useEffect(() => {
    getStudentHistory(user.uid)
      .then(setResults)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [user]);

  if (loading) return <div className="loading-spinner">Loading history...</div>;

  return (
    <div className="dashboard-main fade-in" style={{ maxWidth: 900, margin: "0 auto" }}>
      <div className="page-header">
        <div>
          <button className="back-link" onClick={() => navigate("/student/dashboard")}>
            ← Dashboard
          </button>
          <h1>Exam History</h1>
          <p>Your past exam results</p>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      {results.length === 0 ? (
        <div className="empty-state">
          <span>📋</span>
          <p>No exams taken yet.</p>
        </div>
      ) : (
        <div className="exam-list">
          {results.map(r => (
            <div
              key={r.id}
              className="exam-card live"
              style={{ cursor: "pointer" }}
              onClick={() => navigate(`/results/${r.exam_id}`)}
            >
              <div className="exam-info">
                <h3>{r.exam_title || "Exam"}</h3>
                <div className="exam-meta-row">
                  <span>{r.score} / {r.total}</span>
                  <span>{r.percentage}%</span>
                  <span>{r.submitted_at?.toDate ? r.submitted_at.toDate().toLocaleDateString() : "—"}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
