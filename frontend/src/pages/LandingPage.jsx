/* src/pages/LandingPage.jsx — Modern Split-Screen Portal */
import React from "react";
import { useNavigate } from "react-router-dom";
import { GraduationCap, Zap, ShieldCheck, BarChart, User, Briefcase } from "lucide-react";

export default function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="landing-root fade-in">
      {/* Left Panel: Branding & Visuals */}
      <div className="landing-brand-panel">
        <div className="brand-content">
          <div className="brand-logo">
            <span className="logo-icon"><GraduationCap size={56} color="#0ea5e9" /></span>
            <h1 className="logo-title">ExamProctor</h1>
          </div>
          <p className="brand-tagline">
            Secure, seamless, and intelligent examination management.
          </p>
          <div className="brand-features">
            <div className="feature-item">
              <span className="feat-icon"><Zap size={20} color="#0ea5e9" /></span>
              <p>Real-time analytics and monitoring</p>
            </div>
            <div className="feature-item">
              <span className="feat-icon"><ShieldCheck size={20} color="#0ea5e9" /></span>
              <p>Enterprise-grade secure environments</p>
            </div>
            <div className="feature-item">
              <span className="feat-icon"><BarChart size={20} color="#0ea5e9" /></span>
              <p>Comprehensive performance insights</p>
            </div>
          </div>
        </div>
      </div>

      {/* Right Panel: Role Selection */}
      <div className="landing-auth-panel">
        <div className="auth-selection-container">
          <h2>Welcome back</h2>
          <p className="selection-prompt">Please select your portal to continue</p>
          
          <div className="role-grid">
            <div 
              className="role-card student-card"
              onClick={() => navigate("/student/login")}
            >
              <div className="role-card-header">
                <span className="role-icon"><User size={28} color="#0ea5e9" /></span>
                <h3>Student Portal</h3>
              </div>
              <p>Access your enrolled courses, take active examinations, and review your academic performance.</p>
              <span className="role-arrow">→</span>
            </div>

            <div 
              className="role-card mentor-card"
              onClick={() => navigate("/mentor/login")}
            >
              <div className="role-card-header">
                <span className="role-icon"><Briefcase size={28} color="#0ea5e9" /></span>
                <h3>Faculty Console</h3>
              </div>
              <p>Manage curriculum, create and monitor active exams, and review student behavior analytics.</p>
              <span className="role-arrow">→</span>
            </div>
          </div>
          
          <div className="landing-footer">
            <p>ExamProctor Platform v2.0 &copy; {new Date().getFullYear()}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
