/* src/pages/AdminApproval.jsx — Jaaiwanth's admin panel to approve/reject mentors */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  collection,
  getDocs,
  doc,
  updateDoc,
  deleteDoc,
} from "firebase/firestore";
import { useAuth } from "../context/AuthContext";
import { auth, db } from "../firebase";
import { signOut } from "firebase/auth";

export default function AdminApproval() {
  const { user, role, loading } = useAuth();
  const navigate = useNavigate();
  const [pending, setPending]   = useState([]);
  const [fetching, setFetching] = useState(true);
  const [message, setMessage]   = useState("");

  // Guard: only admin can access this page
  useEffect(() => {
    if (!loading && role !== "admin") {
      navigate("/");
    }
  }, [role, loading, navigate]);

  useEffect(() => {
    if (role === "admin") fetchPending();
  }, [role]);

  async function fetchPending() {
    setFetching(true);
    const snap = await getDocs(collection(db, "pending_mentors"));
    const list = snap.docs
      .map(d => ({ id: d.id, ...d.data() }))
      .filter(m => m.status === "pending");
    setPending(list);
    setFetching(false);
  }

  async function approve(mentor) {
    // Update role in users collection
    await updateDoc(doc(db, "users", mentor.uid), { role: "mentor" });
    // Update pending_mentors status
    await updateDoc(doc(db, "pending_mentors", mentor.uid), { status: "approved" });
    setMessage(`✅ ${mentor.name} approved as mentor.`);
    fetchPending();
  }

  async function reject(mentor) {
    // Set role to rejected
    await updateDoc(doc(db, "users", mentor.uid), { role: "rejected" });
    await updateDoc(doc(db, "pending_mentors", mentor.uid), { status: "rejected" });
    setMessage(`❌ ${mentor.name} rejected.`);
    fetchPending();
  }

  if (loading || fetching) {
    return (
      <div className="auth-root">
        <div className="loading-spinner">Loading...</div>
      </div>
    );
  }

  return (
    <div className="admin-root">
      <div className="admin-header">
        <div>
          <h1>🛡️ Admin Panel</h1>
          <p>Mentor Approval Dashboard</p>
        </div>
        <button className="logout-btn" onClick={() => { signOut(auth); navigate("/"); }}>
          Sign Out
        </button>
      </div>

      {message && <div className="alert success admin-alert">{message}</div>}

      <div className="admin-content">
        <h2>Pending Mentor Requests ({pending.length})</h2>

        {pending.length === 0 ? (
          <div className="empty-state">
            <span>🎉</span>
            <p>No pending requests. All caught up!</p>
          </div>
        ) : (
          <div className="mentor-list">
            {pending.map(mentor => (
              <div key={mentor.uid} className="mentor-card">
                <div className="mentor-info">
                  <div className="mentor-avatar">
                    {mentor.name?.[0]?.toUpperCase() || "M"}
                  </div>
                  <div>
                    <h3>{mentor.name}</h3>
                    <p>{mentor.email}</p>
                    <span className="mentor-date">
                      Requested: {new Date(mentor.requested_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
                <div className="mentor-actions">
                  <button
                    className="approve-btn"
                    onClick={() => approve(mentor)}
                  >
                    ✓ Approve
                  </button>
                  <button
                    className="reject-btn"
                    onClick={() => reject(mentor)}
                  >
                    ✕ Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
