// src/api/events.js — mentor manual-review API (behaviour events, S3 recordings, decisions)
//
// Every call sends the signed-in user's Firebase ID token; the backend only answers
// mentors/admins who own the exam. Recordings are never public: "View Recording"
// asks the backend for a short-lived presigned URL.

import { auth } from "../firebase";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function call(path, { method = "GET", body } = {}) {
  const user = auth.currentUser;
  if (!user) throw new Error("You are not signed in.");
  const token = await user.getIdToken();
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

/** { session, events[] } for one student in one exam */
export function getBehaviourLog(studentUid, examId) {
  return call(`/api/events/${encodeURIComponent(studentUid)}?exam_id=${encodeURIComponent(examId)}`);
}

/** Review status of every student in an exam (PENDING_REVIEW first) */
export async function getExamReviews(examId) {
  return (await call(`/api/exams/${encodeURIComponent(examId)}/reviews`)).sessions;
}

/** Temporary presigned URL for one warning recording */
export async function getRecordingUrl(eventId, examId) {
  return (await call(`/api/events/${encodeURIComponent(eventId)}/recording?exam_id=${encodeURIComponent(examId)}`)).url;
}

/** decision: "CLEARED" | "CONFIRMED_VIOLATION" */
export async function submitReview(eventId, examId, decision, notes) {
  return (await call(`/api/events/${encodeURIComponent(eventId)}/review?exam_id=${encodeURIComponent(examId)}`, {
    method: "PATCH",
    body: { decision, notes },
  })).session;
}

export const REVIEW_LABELS = {
  NOT_REQUIRED: "No review needed",
  PENDING_REVIEW: "Pending Review",
  CLEARED: "Cleared",
  CONFIRMED_VIOLATION: "Confirmed Violation",
};

export const REVIEW_BADGE = {
  NOT_REQUIRED: "badge-muted",
  PENDING_REVIEW: "badge-warn",
  CLEARED: "badge-ok",
  CONFIRMED_VIOLATION: "badge-danger",
};
