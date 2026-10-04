/* src/pages/Results.jsx — Student result page */
import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { getResultBundle } from "../api/examApi";
import ResultsView from "../components/ResultsView.jsx";

export default function Results() {
  const { examId } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();

  const [bundle, setBundle]   = useState(null);
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getResultBundle(examId, user.uid)
      .then(b => (b ? setBundle(b) : setError("No result found for this exam.")))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [examId, user]);

  if (loading) return <div className="loading-spinner">Loading results...</div>;

  if (error || !bundle) {
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

  const { result } = bundle;
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
      <ResultsView bundle={bundle} />
    </div>
  );
}
