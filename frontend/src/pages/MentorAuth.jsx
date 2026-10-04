/* src/pages/MentorAuth.jsx — Mentor Login & Signup */
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
} from "firebase/auth";
import { doc, setDoc, getDoc } from "firebase/firestore";
import { auth, db } from "../firebase";

export default function MentorAuth() {
  const navigate = useNavigate();
  const [mode, setMode]       = useState("login"); // "login" | "signup"
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");
  const [success, setSuccess] = useState("");

  // Form fields
  const [name, setName]         = useState("");
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");

  const clearMessages = () => { setError(""); setSuccess(""); };

  /* ── SIGNUP ────────────────────────────────────────────── */
  async function handleSignup(e) {
    e.preventDefault();
    clearMessages();
    if (!name || !email || !password) return setError("All fields are required.");
    if (password.length < 6) return setError("Password must be at least 6 characters.");

    setLoading(true);
    try {
      const cred = await createUserWithEmailAndPassword(auth, email, password);

      // Save mentor profile — role is "pending" until admin approves
      await setDoc(doc(db, "users", cred.user.uid), {
        name,
        email,
        role: "pending",
        created_at: new Date().toISOString(),
      });

      // Also write to "pending_mentors" collection for admin to see
      await setDoc(doc(db, "pending_mentors", cred.user.uid), {
        name,
        email,
        uid: cred.user.uid,
        requested_at: new Date().toISOString(),
        status: "pending",
      });

      setSuccess(
        "Request submitted! You'll be notified once your account is approved by the admin."
      );
      setMode("login");
    } catch (err) {
      setError(friendlyError(err.code));
    } finally {
      setLoading(false);
    }
  }

  /* ── LOGIN ─────────────────────────────────────────────── */
  async function handleLogin(e) {
    e.preventDefault();
    clearMessages();
    if (!email || !password) return setError("Email and password required.");
    setLoading(true);
    try {
      const cred = await signInWithEmailAndPassword(auth, email, password);

      // Check role in Firestore
      const snap = await getDoc(doc(db, "users", cred.user.uid));
      if (!snap.exists()) {
        setError("Account not found. Please sign up.");
        setLoading(false);
        return;
      }

      const role = snap.data().role;
      if (role === "pending") {
        setError("Your account is pending approval by the admin. Please wait.");
        setLoading(false);
        return;
      }
      if (role !== "mentor" && role !== "admin") {
        setError("This account does not have mentor access.");
        setLoading(false);
        return;
      }

      navigate("/mentor/dashboard");
    } catch (err) {
      setError(friendlyError(err.code));
    } finally {
      setLoading(false);
    }
  }

  function friendlyError(code) {
    const map = {
      "auth/email-already-in-use": "This email is already registered.",
      "auth/invalid-email":        "Invalid email address.",
      "auth/wrong-password":       "Incorrect password.",
      "auth/user-not-found":       "No account found. Please sign up.",
      "auth/weak-password":        "Password is too weak.",
      "auth/too-many-requests":    "Too many attempts. Try again later.",
      "auth/invalid-credential":   "Invalid credentials. Check and try again.",
    };
    return map[code] || "Something went wrong. Please try again.";
  }

  return (
    <div className="auth-root">
      <div className="auth-bg" />
      <div className="auth-card">
        <button className="back-btn" onClick={() => navigate("/")}>← Back</button>

        <div className="auth-header">
          <span className="auth-icon">👩‍🏫</span>
          <h2>{mode === "login" ? "Mentor Login" : "Mentor Sign Up"}</h2>
          <p>
            {mode === "login"
              ? "Sign in to your mentor account"
              : "Request access — approval required"}
          </p>
        </div>

        {error   && <div className="alert error">{error}</div>}
        {success && <div className="alert success">{success}</div>}

        <form onSubmit={mode === "login" ? handleLogin : handleSignup}>
          {mode === "signup" && (
            <div className="field">
              <label>Full Name</label>
              <input
                type="text"
                placeholder="e.g. Dr. Priya R"
                value={name}
                onChange={e => setName(e.target.value)}
              />
            </div>
          )}

          <div className="field">
            <label>Email Address</label>
            <input
              type="email"
              placeholder="mentor@college.edu"
              value={email}
              onChange={e => setEmail(e.target.value)}
            />
          </div>

          <div className="field">
            <label>Password</label>
            <input
              type="password"
              placeholder={mode === "signup" ? "Min. 6 characters" : "Your password"}
              value={password}
              onChange={e => setPassword(e.target.value)}
            />
          </div>

          {mode === "signup" && (
            <div className="signup-note">
              📋 Your request will be reviewed by the admin before you can access the platform.
            </div>
          )}

          <button type="submit" className="submit-btn mentor-btn" disabled={loading}>
            {loading
              ? "Please wait..."
              : mode === "login"
              ? "Sign In"
              : "Request Access"}
          </button>
        </form>

        <div className="auth-switch">
          {mode === "login" ? (
            <>New mentor? <button onClick={() => { setMode("signup"); clearMessages(); }}>Request access</button></>
          ) : (
            <>Already approved? <button onClick={() => { setMode("login"); clearMessages(); }}>Log in</button></>
          )}
        </div>
      </div>
    </div>
  );
}
