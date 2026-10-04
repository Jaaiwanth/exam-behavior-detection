/* src/pages/LandingPage.jsx — Role selector landing page */
import React from "react";
import { useNavigate } from "react-router-dom";

export default function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="landing-root">
      <div className="landing-bg" />

      <div className="landing-card">
        {/* Logo / Brand */}
        <div className="landing-logo">
          <span className="logo-icon">🎓</span>
          <h1 className="logo-title">ExamProctor</h1>
          <p className="logo-sub">AI-Powered Examination Platform</p>
        </div>

        {/* Role Buttons */}
        <p className="landing-prompt">Choose how you want to sign in</p>

        <div className="role-grid">
          <button
            className="role-card student"
            onClick={() => navigate("/student/login")}
          >
            <span className="role-icon">👨‍🎓</span>
            <span className="role-label">Student</span>
            <span className="role-desc">Take exams & view results</span>
          </button>

          <button
            className="role-card mentor"
            onClick={() => navigate("/mentor/login")}
          >
            <span className="role-icon">👩‍🏫</span>
            <span className="role-label">Mentor</span>
            <span className="role-desc">Manage exams & students</span>
          </button>
        </div>

        <p className="landing-footer">
          Secure · Proctored · AI-monitored
        </p>
      </div>
    </div>
  );
}
