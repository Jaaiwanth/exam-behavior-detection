/* src/components/BehaviourReview.jsx — Mentor manual review of one student's warnings for one exam.
   A score of 0 only means "needs a human look"; the mentor's decision here is the final verdict. */
import React, { useCallback, useEffect, useState } from "react";
import {
  getBehaviourLog,
  getRecordingUrl,
  submitReview,
  REVIEW_LABELS,
  REVIEW_BADGE,
} from "../api/events";

export default function BehaviourReview({ student, examId, examTitle }) {
  const [data, setData]       = useState(null);
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(true);

  const [playing, setPlaying]   = useState(null);   // { event, url } | { event, error }
  const [loadingRec, setLoadingRec] = useState(null);

  const [notes, setNotes]     = useState("");
  const [saving, setSaving]   = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const d = await getBehaviourLog(student.uid, examId);
      setData(d);
      setNotes(d.session?.mentor_notes || "");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [student.uid, examId]);

  useEffect(() => { setPlaying(null); setSaveMsg(""); load(); }, [load]);

  async function viewRecording(ev) {
    setLoadingRec(ev.event_id);
    setPlaying(null);
    try {
      // A fresh short-lived URL is requested every time — nothing public, nothing cached.
      const url = await getRecordingUrl(ev.event_id, examId);
      setPlaying({ event: ev, url });
    } catch (err) {
      setPlaying({ event: ev, error: err.message });
    } finally {
      setLoadingRec(null);
    }
  }

  async function decide(decision) {
    const events = data.events;
    if (!events.length) return;
    if (decision === "CONFIRMED_VIOLATION" &&
        !window.confirm(`Confirm a violation for ${student.name}? This records your final decision.`)) return;
    // The decision applies to the whole exam session; anchor it on the score-0 event if there is one.
    const anchor = events.find(e => e.flagged) || events[events.length - 1];
    setSaving(true);
    setSaveMsg("");
    try {
      const session = await submitReview(anchor.event_id, examId, decision, notes);
      setData(prev => ({ ...prev, session }));
      setSaveMsg(`Saved: ${REVIEW_LABELS[decision]}`);
    } catch (err) {
      setSaveMsg(`Could not save: ${err.message}`);
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="loading-spinner">Loading behaviour log...</div>;

  const session = data?.session;
  const events  = data?.events || [];
  const status  = session?.review_status || "NOT_REQUIRED";
  const reviewed = status === "CLEARED" || status === "CONFIRMED_VIOLATION";

  return (
    <section className="detail-card" style={{ marginBottom: 20 }}>
      <div className="review-header">
        <h2>🚩 Behaviour Log</h2>
        <span className={`badge ${REVIEW_BADGE[status]}`}>{REVIEW_LABELS[status]}</span>
      </div>

      {error && <div className="alert error">{error}</div>}

      {!error && (
        <>
          <div className="review-summary">
            <div><span>Student</span><strong>{student.name}</strong><em>{student.reg_no || student.email}</em></div>
            <div><span>Exam</span><strong>{examTitle}</strong></div>
            <div>
              <span>Integrity score</span>
              <strong style={{ color: (session?.last_score ?? 100) === 0 ? "var(--danger)" : undefined }}>
                {session ? `${session.last_score} / 100` : "100 / 100"}
              </strong>
            </div>
            <div><span>Warnings</span><strong>{session?.warning_count ?? 0}</strong></div>
          </div>

          {status === "PENDING_REVIEW" && (
            <div className="alert error" style={{ marginTop: 12 }}>
              The integrity score reached 0, so this exam needs your manual review. This is{" "}
              <b>not</b> an automatic violation — watch the recordings and decide below.
            </div>
          )}

          {events.length === 0 ? (
            <p className="detail-hint" style={{ marginTop: 12 }}>No warnings were recorded for this exam.</p>
          ) : (
            <table className="leaderboard-table" style={{ marginTop: 14 }}>
              <thead>
                <tr><th>Time</th><th>Warning</th><th>Score</th><th>Recording</th></tr>
              </thead>
              <tbody>
                {events.map(ev => (
                  <tr key={ev.event_id} className={playing?.event.event_id === ev.event_id ? "top-rank" : ""}>
                    <td className="ts-cell">{new Date(ev.timestamp).toLocaleString()}</td>
                    <td>{ev.warning_type}{ev.flagged && <span className="badge badge-danger" style={{ marginLeft: 8 }}>score 0</span>}</td>
                    <td>{ev.sanity_score ?? "—"}</td>
                    <td>
                      <button
                        className="exam-detail-btn"
                        disabled={!ev.has_recording || loadingRec === ev.event_id}
                        title={ev.has_recording ? "" : ev.recording_status === "PENDING" ? "Still processing" : "No recording"}
                        onClick={() => viewRecording(ev)}
                      >
                        {loadingRec === ev.event_id ? "Loading…"
                          : ev.has_recording ? "▶ View Recording"
                          : ev.recording_status === "PENDING" ? "Processing…" : "Unavailable"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {playing && (
            <div className="recording-box">
              <p className="detail-hint">
                {playing.event.warning_type} — {new Date(playing.event.timestamp).toLocaleString()}
                {!playing.error && " (link expires in a few minutes; click View Recording again if playback stops)"}
              </p>
              {playing.error
                ? <div className="alert error">{playing.error}</div>
                : <video src={playing.url} controls autoPlay playsInline className="recording-video" />}
            </div>
          )}

          {events.length > 0 && (
            <div className="review-decision">
              <h3>Your decision</h3>
              {reviewed && (
                <p className="detail-hint">
                  Decided {session.reviewed_at ? new Date(session.reviewed_at).toLocaleString() : ""}.
                  You can change it until you are sure.
                </p>
              )}
              <textarea
                className="student-input"
                rows={3}
                placeholder="Notes (optional) — what you saw in the recordings"
                value={notes}
                onChange={e => setNotes(e.target.value)}
              />
              <div className="exam-actions">
                <button className="live-toggle-btn" disabled={saving} onClick={() => decide("CLEARED")}>
                  ✓ Clear student
                </button>
                <button className="live-toggle-btn live" disabled={saving} onClick={() => decide("CONFIRMED_VIOLATION")}>
                  ⚠ Confirm violation
                </button>
              </div>
              {saveMsg && <p className="detail-hint" style={{ marginTop: 10 }}>{saveMsg}</p>}
            </div>
          )}
        </>
      )}
    </section>
  );
}
