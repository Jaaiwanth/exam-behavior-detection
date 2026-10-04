/* src/pages/StudentAuth.jsx — Student Login & Signup */
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  sendEmailVerification,
} from "firebase/auth";
import { doc, setDoc, getDoc } from "firebase/firestore";
import { auth, db } from "../firebase";

export default function StudentAuth() {
  const navigate = useNavigate();
  const [mode, setMode]       = useState("login"); // "login" | "signup"
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");
  const [success, setSuccess] = useState("");

  // Form fields
  const [name, setName]     = useState("");
  const [regNo, setRegNo]   = useState("");
  const [email, setEmail]   = useState("");
  const [password, setPassword] = useState("");

  const clearMessages = () => { setError(""); setSuccess(""); };

  /* ── SIGNUP ───────────────────────────────────────────── */
  async function handleSignup(e) {
    e.preventDefault();
    clearMessages();
    if (!name || !regNo || !email || !password) {
      return setError("All fields are required.");
    }
    if (password.length < 6) {
      return setError("Password must be at least 6 characters.");
    }
    setLoading(true);
    try {
      const cred = await createUserWithEmailAndPassword(auth, email, password);
      await sendEmailVerification(cred.user);

      // Save student profile to Firestore
      await setDoc(doc(db, "users", cred.user.uid), {
        name,
        reg_no: regNo,
        email,
        role: "student",
        created_at: new Date().toISOString(),
      });

      setSuccess(
        "Account created! Check your email to verify your account, then log in."
      );
      setMode("login");
    } catch (err) {
      setError(friendlyError(err.code));
    } finally {
      setLoading(false);
    }
  }

  /* ── LOGIN ────────────────────────────────────────────── */
  async function handleLogin(e) {
    e.preventDefault();
    clearMessages();
    if (!regNo || !password) return setError("Registration number and password required.");
    setLoading(true);
    try {
      // Fetch email from Firestore by reg_no
      // We store reg_no→uid mapping in a separate collection for quick lookup
      const mapSnap = await getDoc(doc(db, "reg_map", regNo));
      let loginEmail = email;

      if (mapSnap.exists()) {
        loginEmail = mapSnap.data().email;
      } else if (!loginEmail) {
        setError("Registration number not found. Please sign up first.");
        setLoading(false);
        return;
      }

      const cred = await signInWithEmailAndPassword(auth, loginEmail, password);

      if (!cred.user.emailVerified) {
        setError("Please verify your email before logging in.");
        setLoading(false);
        return;
      }

      navigate("/student/dashboard");
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
          <span className="auth-icon">👨‍🎓</span>
          <h2>{mode === "login" ? "Student Login" : "Student Sign Up"}</h2>
          <p>{mode === "login" ? "Sign in with your registration number" : "Create your student account"}</p>
        </div>

        {error   && <div className="alert error">{error}</div>}
        {success && <div className="alert success">{success}</div>}

        <form onSubmit={mode === "login" ? handleLogin : handleSignup}>
          {mode === "signup" && (
            <div className="field">
              <label>Full Name</label>
              <input
                type="text"
                placeholder="e.g. Jaaiwanth S"
                value={name}
                onChange={e => setName(e.target.value)}
              />
            </div>
          )}

          <div className="field">
            <label>Registration Number</label>
            <input
              type="text"
              placeholder="e.g. RA2011003010234"
              value={regNo}
              onChange={e => setRegNo(e.target.value)}
            />
          </div>

          {mode === "signup" && (
            <div className="field">
              <label>Email Address</label>
              <input
                type="email"
                placeholder="your@email.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
              />
            </div>
          )}

          {mode === "login" && (
            <div className="field">
              <label>Email Address <span className="field-hint">(needed to look up your account)</span></label>
              <input
                type="email"
                placeholder="your@email.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
              />
            </div>
          )}

          <div className="field">
            <label>Password</label>
            <input
              type="password"
              placeholder={mode === "signup" ? "Min. 6 characters" : "Your password"}
              value={password}
              onChange={e => setPassword(e.target.value)}
            />
          </div>

          <button type="submit" className="submit-btn student-btn" disabled={loading}>
            {loading ? "Please wait..." : mode === "login" ? "Sign In" : "Create Account"}
          </button>
        </form>

        <div className="auth-switch">
          {mode === "login" ? (
            <>Don&apos;t have an account? <button onClick={() => { setMode("signup"); clearMessages(); }}>Sign up</button></>
          ) : (
            <>Already have an account? <button onClick={() => { setMode("login"); clearMessages(); }}>Log in</button></>
          )}
        </div>
      </div>
    </div>
  );
}
