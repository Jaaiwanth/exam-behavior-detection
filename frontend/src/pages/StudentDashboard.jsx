/* src/pages/StudentDashboard.jsx — Student home: courses + exams */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { signOut } from "firebase/auth";
import { doc, getDoc } from "firebase/firestore";
import { auth, db } from "../firebase";
import { useAuth } from "../context/AuthContext";
import {
  getAllCourses,
  getStudentEnrollments,
  getCourseExams,
} from "../api/examApi";

export default function StudentDashboard() {
  const { user } = useAuth();
  const navigate  = useNavigate();

  const [profile, setProfile]         = useState(null);
  const [courses, setCourses]         = useState([]);
  const [enrolledIds, setEnrolledIds] = useState([]);
  const [activeTab, setActiveTab]     = useState("courses"); // "courses" | "exams"
  const [selectedCourse, setSelectedCourse] = useState(null);
  const [exams, setExams]             = useState([]);
  const [loading, setLoading]         = useState(true);

  useEffect(() => {
    if (user) loadData();
  }, [user]);

  async function loadData() {
    setLoading(true);
    const [profileSnap, allCourses, myEnrollments] = await Promise.all([
      getDoc(doc(db, "users", user.uid)),
      getAllCourses(),
      getStudentEnrollments(user.uid),
    ]);
    setProfile(profileSnap.data());
    setCourses(allCourses);
    setEnrolledIds(myEnrollments);
    setLoading(false);
  }

  async function openCourse(course) {
    setSelectedCourse(course);
    setActiveTab("exams");
    const courseExams = await getCourseExams(course.id);
    setExams(courseExams);
  }

  async function handleLogout() {
    await signOut(auth);
    navigate("/");
  }

  if (loading) return <div className="loading-spinner">Loading dashboard...</div>;

  const enrolledCourses = courses.filter(c => enrolledIds.includes(c.id));

  return (
    <div className="dashboard-root">
      {/* ── Sidebar ──────────────────────────────────────────── */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-icon">🎓</span>
          <span className="brand-name">ExamProctor</span>
        </div>

        <div className="sidebar-profile">
          <div className="profile-avatar">
            {profile?.name?.[0]?.toUpperCase() || "S"}
          </div>
          <div>
            <p className="profile-name">{profile?.name || "Student"}</p>
            <p className="profile-meta">{profile?.reg_no}</p>
          </div>
        </div>

        <nav className="sidebar-nav">
          <button
            className={`nav-item ${activeTab === "courses" ? "active" : ""}`}
            onClick={() => setActiveTab("courses")}
          >
            📚 Courses
          </button>
          <button
            className={`nav-item ${activeTab === "history" ? "active" : ""}`}
            onClick={() => navigate("/student/history")}
          >
            📋 Exam History
          </button>
        </nav>

        <button className="sidebar-logout" onClick={handleLogout}>
          ⬡ Sign Out
        </button>
      </aside>

      {/* ── Main content ─────────────────────────────────────── */}
      <main className="dashboard-main">

        {/* COURSES TAB */}
        {activeTab === "courses" && (
          <div className="fade-in">
            <div className="page-header">
              <h1>My Courses</h1>
              <p>Courses your mentor has added you to</p>
            </div>

            {/* Enrolled courses */}
            {enrolledCourses.length > 0 && (
              <section className="section">
                <h2 className="section-title">Enrolled</h2>
                <div className="course-grid">
                  {enrolledCourses.map(c => (
                    <div key={c.id} className="course-card enrolled" onClick={() => openCourse(c)}>
                      <div className="course-icon">☁️</div>
                      <h3>{c.name}</h3>
                      <p className="course-meta">Enrolled</p>
                      <button className="course-btn">View Exams →</button>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {enrolledCourses.length === 0 && (
              <div className="empty-state">
                <span>📭</span>
                <p>You have not been added to any course yet. Ask your mentor to add you.</p>
              </div>
            )}
          </div>
        )}

        {/* EXAMS TAB */}
        {activeTab === "exams" && selectedCourse && (
          <div className="fade-in">
            <div className="page-header">
              <button className="back-link" onClick={() => setActiveTab("courses")}>
                ← Back to Courses
              </button>
              <h1>{selectedCourse.name}</h1>
              <p>Available exams in this course</p>
            </div>

            {exams.length === 0 ? (
              <div className="empty-state">
                <span>📝</span>
                <p>No exams published yet. Check back later!</p>
              </div>
            ) : (
              <div className="exam-list">
                {exams.map(exam => (
                  <div key={exam.id} className={`exam-card ${exam.is_live ? "live" : "closed"}`}>
                    <div className="exam-info">
                      <div className="exam-title-row">
                        <h3>{exam.title}</h3>
                        {exam.is_live
                          ? <span className="badge badge-ok">🟢 Live</span>
                          : <span className="badge badge-muted">🔒 Closed</span>
                        }
                      </div>
                      <div className="exam-meta-row">
                        <span>📊 {exam.pick_n} Questions</span>
                        <span>⏱ {Math.floor(exam.duration_sec / 60)} minutes</span>
                      </div>
                    </div>
                    <button
                      className={`exam-start-btn ${!exam.is_live ? "disabled" : ""}`}
                      disabled={!exam.is_live}
                      onClick={() => navigate(`/exam/${exam.id}`)}
                    >
                      {exam.is_live ? "Start Exam →" : "Not Available"}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
