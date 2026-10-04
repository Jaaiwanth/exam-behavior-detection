/* src/pages/MentorDashboard.jsx — Full mentor panel */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { signOut } from "firebase/auth";
import { doc, getDoc } from "firebase/firestore";
import * as XLSX from "xlsx";
import { GraduationCap } from "lucide-react";
import { auth, db } from "../firebase";
import { useAuth } from "../context/AuthContext";
import StudentDetail from "../components/StudentDetail.jsx";
import { getExamReviews, REVIEW_LABELS, REVIEW_BADGE } from "../api/events";
import {
  createCourse,
  getMentorCourses,
  getCourseExams,
  createExam,
  uploadQuestions,
  getQuestionBank,
  setExamLive,
  getCourseStudentProfiles,
  findStudent,
  enrollStudent,
  unenrollStudent,
  getUserProfiles,
  getExamLeaderboard,
} from "../api/examApi";

export default function MentorDashboard() {
  const { user } = useAuth();
  const navigate  = useNavigate();

  const [profile, setProfile]           = useState(null);
  const [courses, setCourses]           = useState([]);
  const [selectedCourse, setSelectedCourse] = useState(null);
  const [exams, setExams]               = useState([]);
  const [selectedExam, setSelectedExam] = useState(null);
  const [questions, setQuestions]       = useState([]);
  const [leaderboard, setLeaderboard]   = useState([]);
  const [activeTab, setActiveTab]       = useState("courses");

  // Modals
  const [showCreateCourse, setShowCreateCourse] = useState(false);
  const [showCreateExam, setShowCreateExam]     = useState(false);

  // Form fields
  const [courseName, setCourseName]     = useState("");
  const [examTitle, setExamTitle]       = useState("");
  const [examPickN, setExamPickN]       = useState(20);
  const [examDuration, setExamDuration] = useState(10);

  // Upload state
  const [uploadFile, setUploadFile]     = useState(null);
  const [uploadPreview, setUploadPreview] = useState([]);
  const [uploading, setUploading]       = useState(false);
  const [uploadMsg, setUploadMsg]       = useState("");

  // Students tab
  const [students, setStudents]         = useState([]);
  const [studentInput, setStudentInput] = useState("");
  const [addingStudents, setAddingStudents] = useState(false);
  const [studentMsgs, setStudentMsgs]   = useState([]);
  const [selectedStudent, setSelectedStudent] = useState(null);
  const [names, setNames]               = useState({}); // uid -> profile, for the leaderboard
  const [reviews, setReviews]           = useState([]);  // behaviour-review sessions for the open exam
  const [reviewsError, setReviewsError] = useState("");
  const [reviewExamId, setReviewExamId] = useState(null); // exam to open in the student detail view

  const [loading, setLoading]           = useState(true);
  const [saving, setSaving]             = useState(false);
  const [message, setMessage]           = useState("");

  useEffect(() => {
    if (user) loadData();
  }, [user]);

  async function loadData() {
    setLoading(true);
    const [profileSnap, mentorCourses] = await Promise.all([
      getDoc(doc(db, "users", user.uid)),
      getMentorCourses(user.uid),
    ]);
    setProfile(profileSnap.data());
    setCourses(mentorCourses);
    setLoading(false);
  }

  async function handleSelectCourse(course) {
    setSelectedCourse(course);
    setSelectedExam(null);
    setActiveTab("exams");
    const courseExams = await getCourseExams(course.id);
    setExams(courseExams);
  }

  async function handleSelectExam(exam) {
    setSelectedExam(exam);
    setActiveTab("examDetail");
    const [bank, lb] = await Promise.all([
      getQuestionBank(exam.id),
      getExamLeaderboard(exam.id),
    ]);
    setQuestions(bank);
    setLeaderboard(lb);
    setNames(await getUserProfiles(lb.map(r => r.student_uid)));
    loadReviews(exam.id);
  }

  async function loadReviews(examId) {
    setReviews([]);
    setReviewsError("");
    try {
      const sessions = await getExamReviews(examId);
      setReviews(sessions);
      const profiles = await getUserProfiles(sessions.map(x => x.student_id));
      setNames(prev => ({ ...prev, ...profiles }));
    } catch (err) {
      setReviewsError(err.message);
    }
  }

  function openReview(session) {
    const p = names[session.student_id] || {};
    setSelectedStudent({ uid: session.student_id, name: p.name || session.student_id, reg_no: p.reg_no, email: p.email });
    setReviewExamId(selectedExam.id);
    setActiveTab("students");
  }

  /* ── Students ──────────────────────────────────────────── */
  async function openStudents() {
    setActiveTab("students");
    setSelectedStudent(null);
    setReviewExamId(null);
    setStudentMsgs([]);
    setStudents(await getCourseStudentProfiles(selectedCourse.id));
  }

  async function handleAddStudents(e) {
    e.preventDefault();
    const ids = [...new Set(studentInput.split(/[\n,;]+/).map(x => x.trim()).filter(Boolean))];
    if (!ids.length) return;
    setAddingStudents(true);
    const enrolledUids = new Set(students.map(st => st.uid));
    const msgs = [];
    for (const id of ids) {
      try {
        const st = await findStudent(id);
        if (!st) msgs.push({ ok: false, text: `${id}: no registered student found` });
        else if (enrolledUids.has(st.uid)) msgs.push({ ok: false, text: `${id}: already in this course` });
        else {
          await enrollStudent(selectedCourse.id, st.uid);
          enrolledUids.add(st.uid);
          msgs.push({ ok: true, text: `${st.name} (${id}) added` });
        }
      } catch (err) {
        msgs.push({ ok: false, text: `${id}: ${err.message}` });
      }
    }
    setStudentMsgs(msgs);
    if (msgs.some(m => m.ok)) setStudentInput("");
    setStudents(await getCourseStudentProfiles(selectedCourse.id));
    setAddingStudents(false);
  }

  async function handleRemoveStudent(st) {
    if (!window.confirm(`Remove ${st.name || st.uid} from ${selectedCourse.name}?`)) return;
    await unenrollStudent(selectedCourse.id, st.uid);
    setStudents(prev => prev.filter(x => x.uid !== st.uid));
  }

  /* ── Create Course ─────────────────────────────────────── */
  async function handleCreateCourse(e) {
    e.preventDefault();
    if (!courseName.trim()) return;
    setSaving(true);
    try {
      await createCourse({ name: courseName.trim(), mentorUid: user.uid });
      setCourses(await getMentorCourses(user.uid));
    } catch (err) {
      setSaving(false);
      return setMessage(`Could not create course: ${err.message}`);
    }
    setCourseName("");
    setShowCreateCourse(false);
    setSaving(false);
    setMessage(`Course "${courseName}" created!`);
    setTimeout(() => setMessage(""), 3000);
  }

  /* ── Create Exam ───────────────────────────────────────── */
  async function handleCreateExam(e) {
    e.preventDefault();
    if (!examTitle.trim() || !selectedCourse) return;
    setSaving(true);
    try {
      await createExam({
        courseId: selectedCourse.id,
        title: examTitle.trim(),
        pickN: examPickN,
        durationSec: examDuration * 60,
        mentorUid: user.uid,
      });
      setExams(await getCourseExams(selectedCourse.id));
    } catch (err) {
      setSaving(false);
      return setMessage(`Could not create exam: ${err.message}`);
    }
    setExamTitle("");
    setExamPickN(20);
    setExamDuration(10);
    setShowCreateExam(false);
    setSaving(false);
    setMessage("Exam created! Upload questions to make it live.");
    setTimeout(() => setMessage(""), 4000);
  }

  /* ── Excel Upload ──────────────────────────────────────── */
  function handleFileChange(e) {
    const file = e.target.files[0];
    if (!file) return;
    setUploadFile(file);
    setUploadMsg("");

    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        const wb = XLSX.read(evt.target.result, { type: "binary" });
        const ws = wb.Sheets[wb.SheetNames[0]];
        const rows = XLSX.utils.sheet_to_json(ws, { header: 1 });

        // Skip header row if first cell looks like "question" (case-insensitive)
        const dataRows = rows[0]?.[0]?.toString().toLowerCase().includes("question")
          ? rows.slice(1)
          : rows;

        const parsed = [];
        const problems = [];
        dataRows.filter(r => r[0]).forEach((r, i) => {
          const correct = String(r[5] ?? "").toUpperCase().trim();
          const opts = [r[1], r[2], r[3], r[4]];
          const rowNo = i + 1 + (dataRows === rows ? 0 : 1);
          if (!["A", "B", "C", "D"].includes(correct)) {
            problems.push(`row ${rowNo}: correct answer must be A/B/C/D`);
          } else if (opts.some(o => o === undefined || o === "")) {
            problems.push(`row ${rowNo}: all four options are required`);
          } else {
            parsed.push({
              question: String(r[0]),
              opt_a: String(r[1]),
              opt_b: String(r[2]),
              opt_c: String(r[3]),
              opt_d: String(r[4]),
              correct,
              topic: r[6] ? String(r[6]) : "General",
            });
          }
        });
        if (problems.length) {
          setUploadMsg(
            `Skipped ${problems.length} invalid row(s): ${problems.slice(0, 3).join("; ")}${problems.length > 3 ? "…" : ""}`
          );
        }

        setUploadPreview(parsed);
      } catch {
        setUploadMsg("Failed to parse Excel file. Check the format.");
      }
    };
    reader.readAsBinaryString(file);
  }

  async function handleUploadQuestions() {
    if (!uploadPreview.length || !selectedExam) return;
    setUploading(true);
    try {
      const count = await uploadQuestions(selectedExam.id, uploadPreview);
      setQuestions(await getQuestionBank(selectedExam.id));
      // Update exam in local state
      const courseExams = await getCourseExams(selectedCourse.id);
      setExams(courseExams);
      setSelectedExam(prev => ({ ...prev, total_q: count }));
      setUploadPreview([]);
      setUploadFile(null);
      setUploadMsg(`✅ ${count} questions uploaded successfully!`);
    } catch (err) {
      setUploadMsg(`Error: ${err.message}`);
    } finally {
      setUploading(false);
    }
  }

  /* ── Toggle Live ───────────────────────────────────────── */
  async function handleToggleLive(exam) {
    if (!exam.is_live) {
      if (!exam.total_q) {
        setMessage("Upload questions before making the exam live.");
        return setTimeout(() => setMessage(""), 4000);
      }
      if (exam.pick_n > exam.total_q) {
        setMessage(`Exam picks ${exam.pick_n} questions but the bank has only ${exam.total_q}.`);
        return setTimeout(() => setMessage(""), 4000);
      }
    }
    await setExamLive(exam.id, !exam.is_live);
    const courseExams = await getCourseExams(selectedCourse.id);
    setExams(courseExams);
    if (selectedExam?.id === exam.id) {
      setSelectedExam(prev => ({ ...prev, is_live: !prev.is_live }));
    }
  }

  async function handleLogout() {
    await signOut(auth);
    navigate("/");
  }

  if (loading) return <div className="loading-spinner">Loading dashboard...</div>;

  return (
    <div className="dashboard-root">
      {/* ── Sidebar ──────────────────────────────────────────── */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-icon"><GraduationCap size={32} color="#0ea5e9" /></span>
          <span className="brand-name">ExamProctor</span>
        </div>

        <div className="sidebar-profile">
          <div className="profile-avatar mentor-avatar-color">
            {profile?.name?.[0]?.toUpperCase() || "M"}
          </div>
          <div>
            <p className="profile-name">{profile?.name || "Mentor"}</p>
            <p className="profile-meta">Mentor</p>
          </div>
        </div>

        <nav className="sidebar-nav">
          <button
            className={`nav-item ${activeTab === "courses" ? "active" : ""}`}
            onClick={() => setActiveTab("courses")}
          >
            Courses
          </button>
          {selectedCourse && (
            <button
              className={`nav-item sub ${activeTab === "exams" ? "active" : ""}`}
              onClick={() => setActiveTab("exams")}
            >
              Exams
            </button>
          )}
          {selectedCourse && (
            <button
              className={`nav-item sub ${activeTab === "students" ? "active" : ""}`}
              onClick={openStudents}
            >
              Students
            </button>
          )}
          {selectedExam && (
            <button
              className={`nav-item sub ${activeTab === "examDetail" ? "active" : ""}`}
              onClick={() => setActiveTab("examDetail")}
            >
              Exam Configuration
            </button>
          )}
        </nav>

        <button className="sidebar-logout" onClick={handleLogout}>
          Sign Out
        </button>
      </aside>

      {/* ── Main ─────────────────────────────────────────────── */}
      <main className="dashboard-main">
        {message && <div className="alert success top-alert">{message}</div>}

        {/* COURSES TAB */}
        {activeTab === "courses" && (
          <div className="fade-in">
            <div className="page-header">
              <div>
                <h1>My Courses</h1>
                <p>Manage your enrolled subjects and examination modules</p>
              </div>
              <button className="action-btn" onClick={() => setShowCreateCourse(true)}>
                + New Course
              </button>
            </div>

            {courses.length === 0 ? (
              <div className="empty-state">
                <p>No courses found. Create your first course to begin.</p>
              </div>
            ) : (
              <div className="course-grid">
                {courses.map(c => (
                  <div
                    key={c.id}
                    className="course-card mentor-card"
                    onClick={() => handleSelectCourse(c)}
                  >
                    <div className="course-icon" style={{ background: "var(--brand-navy)", color: "#fff", width: "48px", height: "48px", borderRadius: "8px", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "1.5rem", fontWeight: "700" }}>
                      {c.name.charAt(0).toUpperCase()}
                    </div>
                    <h3>{c.name}</h3>
                    <p className="course-meta">Click to manage exams →</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* EXAMS TAB */}
        {activeTab === "exams" && selectedCourse && (
          <div className="fade-in">
            <div className="page-header">
              <div>
                <button className="back-link" onClick={() => setActiveTab("courses")}>
                  <svg fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
                  <span>Back to Courses</span>
                </button>
                <h1>{selectedCourse.name}</h1>
                <p>Active and drafted examinations</p>
              </div>
              <div className="exam-actions">
                <button className="modal-cancel" onClick={openStudents}>Manage Roster</button>
                <button className="action-btn" onClick={() => setShowCreateExam(true)}>
                  + New Exam
                </button>
              </div>
            </div>

            {exams.length === 0 ? (
              <div className="empty-state">
                <p>No exams created yet. Create an exam and upload questions to begin.</p>
              </div>
            ) : (
              <div className="exam-list">
                {exams.map(exam => (
                  <div key={exam.id} className={`exam-card ${exam.is_live ? "live" : "closed"}`}>
                    <div className="exam-info" onClick={() => handleSelectExam(exam)}>
                      <div className="exam-title-row">
                        <h3>{exam.title}</h3>
                        {exam.is_live
                          ? <span className="badge badge-ok">• Live</span>
                          : <span className="badge badge-muted">Draft</span>
                        }
                      </div>
                      <div className="exam-meta-row">
                        <span>{exam.pick_n} / {exam.total_q} Questions</span>
                        <span>{Math.floor(exam.duration_sec / 60)} min duration</span>
                      </div>
                    </div>
                    <div className="exam-actions">
                      <button
                        className="exam-detail-btn"
                        onClick={() => handleSelectExam(exam)}
                      >
                        Manage
                      </button>
                      <button
                        className={`live-toggle-btn ${exam.is_live ? "live" : ""}`}
                        onClick={() => handleToggleLive(exam)}
                      >
                        {exam.is_live ? "Close Exam" : "Go Live"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* STUDENTS TAB */}
        {activeTab === "students" && selectedCourse && selectedStudent && (
          <StudentDetail
            course={selectedCourse}
            student={selectedStudent}
            exams={exams}
            initialExamId={reviewExamId}
            onBack={() => { setSelectedStudent(null); setReviewExamId(null); }}
          />
        )}

        {activeTab === "students" && selectedCourse && !selectedStudent && (
          <div className="fade-in">
            <div className="page-header">
              <div>
                <button className="back-link" onClick={() => setActiveTab("exams")}>
                  <svg fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
                  <span>Exams</span>
                </button>
                <h1>{selectedCourse.name} — Students</h1>
                <p>Only students you add here can see this course and take its exams</p>
              </div>
            </div>

            <div className="detail-grid">
              <section className="detail-card">
                <h2>Add Students</h2>
                <p className="detail-hint">
                  Enter registration numbers or emails, one per line or comma-separated.
                  Students must have signed up first.
                </p>
                <form onSubmit={handleAddStudents}>
                  <textarea
                    className="student-input"
                    rows={5}
                    placeholder={"21BCE1234\nstudent@college.edu"}
                    value={studentInput}
                    onChange={e => setStudentInput(e.target.value)}
                  />
                  <button type="submit" className="action-btn" disabled={addingStudents || !studentInput.trim()}>
                    {addingStudents ? "Adding..." : "Add to Course"}
                  </button>
                </form>
                {studentMsgs.map((m, i) => (
                  <div key={i} className={`alert ${m.ok ? "success" : "error"}`}>{m.text}</div>
                ))}
              </section>

              <section className="detail-card">
                <h2>Enrolled Directory ({students.length})</h2>
                {students.length === 0 ? (
                  <p className="detail-hint">No students added yet.</p>
                ) : (
                  <div className="question-list">
                    {students.map(st => (
                      <div key={st.uid} className="question-row">
                        <span className="q-text">
                          {st.name}
                          <span className="q-topic"> · {st.reg_no || st.email}</span>
                        </span>
                        <div className="exam-actions">
                          <button className="exam-detail-btn" onClick={() => setSelectedStudent(st)}>
                            Results
                          </button>
                          <button className="exam-detail-btn" onClick={() => navigate(`/mentor/live/${st.uid}`)}>
                            • Live Monitor
                          </button>
                          <button className="modal-cancel" onClick={() => handleRemoveStudent(st)}>
                            Remove
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
          </div>
        )}

        {/* EXAM DETAIL TAB */}
        {activeTab === "examDetail" && selectedExam && (
          <div className="fade-in">
            <div className="page-header">
              <div>
                <button className="back-link" onClick={() => setActiveTab("exams")}>
                  <svg fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
                  <span>Exams</span>
                </button>
                <h1>{selectedExam.title}</h1>
                <p>
                  {selectedExam.pick_n} questions · {Math.floor(selectedExam.duration_sec / 60)} min ·{" "}
                  {selectedExam.is_live
                    ? <span style={{ color: "var(--ok)", fontWeight: "600" }}>• Live</span>
                    : <span style={{ color: "var(--text-muted)", fontWeight: "600" }}>Draft</span>
                  }
                </p>
              </div>
              <button
                className={`live-toggle-btn lg ${selectedExam.is_live ? "live" : ""}`}
                onClick={() => handleToggleLive(selectedExam)}
              >
                {selectedExam.is_live ? "Close Exam" : "Go Live"}
              </button>
            </div>

            <div className="detail-grid">
              {/* Upload Questions */}
              <section className="detail-card">
                <h2>Upload Question Bank</h2>
                <p className="detail-hint">
                  Excel format: Question | Option A | B | C | D | Correct (A/B/C/D) | Topic
                </p>

                <label className="file-upload-area">
                  <input
                    type="file"
                    accept=".xlsx,.xls,.csv"
                    onChange={handleFileChange}
                    style={{ display: "none" }}
                  />
                  <svg className="upload-icon" style={{ width: 48, height: 48, color: "var(--brand-navy)" }} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path></svg>
                  <span>{uploadFile ? uploadFile.name : "Click to choose Excel file"}</span>
                </label>

                {uploadPreview.length > 0 && (
                  <div className="upload-preview">
                    <p className="preview-count">{uploadPreview.length} questions parsed — preview:</p>
                    <div className="preview-table-wrap">
                      <table className="preview-table">
                        <thead>
                          <tr>
                            <th>#</th>
                            <th>Question</th>
                            <th>Correct</th>
                            <th>Topic</th>
                          </tr>
                        </thead>
                        <tbody>
                          {uploadPreview.slice(0, 5).map((q, i) => (
                            <tr key={i}>
                              <td>{i + 1}</td>
                              <td className="q-cell">{q.question.slice(0, 50)}{q.question.length > 50 ? "…" : ""}</td>
                              <td><span className="correct-badge">{q.correct}</span></td>
                              <td>{q.topic}</td>
                            </tr>
                          ))}
                          {uploadPreview.length > 5 && (
                            <tr>
                              <td colSpan={4} className="more-row">
                                + {uploadPreview.length - 5} more questions
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                    <button
                      className="upload-confirm-btn"
                      onClick={handleUploadQuestions}
                      disabled={uploading}
                    >
                      {uploading ? "Uploading..." : `Upload ${uploadPreview.length} Questions`}
                    </button>
                  </div>
                )}

                {uploadMsg && (
                  <div className={`alert ${uploadMsg.startsWith("✅") || uploadMsg.toLowerCase().includes("successfully") ? "success" : "error"}`}>
                    {uploadMsg.replace("✅ ", "")}
                  </div>
                )}
              </section>

              {/* Question Bank */}
              <section className="detail-card">
                <h2>Question Bank ({questions.length})</h2>
                {questions.length === 0 ? (
                  <p className="detail-hint">No questions uploaded yet.</p>
                ) : (
                  <div className="question-list">
                    {questions.slice(0, 10).map((q, i) => (
                      <div key={q.id} className="question-row">
                        <span className="q-num">{i + 1}</span>
                        <span className="q-text">{q.question.slice(0, 70)}{q.question.length > 70 ? "…" : ""}</span>
                        <span className="q-topic">{q.topic}</span>
                        <span className="correct-badge">{q.correct}</span>
                      </div>
                    ))}
                    {questions.length > 10 && (
                      <p className="more-row">+ {questions.length - 10} more</p>
                    )}
                  </div>
                )}
              </section>

              {/* Behaviour review queue */}
              <section className="detail-card full-width">
                <h2>
                  Behaviour Review Queue
                  {reviews.some(r => r.review_status === "PENDING_REVIEW") && (
                    <span className="badge badge-warn" style={{ marginLeft: 10 }}>
                      {reviews.filter(r => r.review_status === "PENDING_REVIEW").length} pending
                    </span>
                  )}
                </h2>
                <p className="detail-hint">
                  Students whose integrity score reached 0 need your manual review. A score of 0 is a flag, not a verdict.
                </p>
                {reviews.length === 0 && (
                  <p className="detail-hint">No behaviour warnings recorded for this exam.</p>
                )}
                {reviews.length > 0 && (
                  <table className="leaderboard-table">
                    <thead>
                      <tr><th>Student</th><th>Warnings</th><th>Score</th><th>Status</th><th></th></tr>
                    </thead>
                    <tbody>
                      {reviews.map(r => (
                        <tr key={r.student_id} className={r.review_status === "PENDING_REVIEW" ? "top-rank" : ""}>
                          <td>{names[r.student_id]?.name || r.student_id}</td>
                          <td>{r.warning_count}</td>
                          <td>{r.last_score} / 100</td>
                          <td><span className={`badge ${REVIEW_BADGE[r.review_status]}`}>{REVIEW_LABELS[r.review_status]}</span></td>
                          <td><button className="exam-detail-btn" onClick={() => openReview(r)}>Open</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>

              {/* Leaderboard */}
              <section className="detail-card full-width">
                <h2>Leaderboard ({leaderboard.length} submissions)</h2>
                {leaderboard.length === 0 ? (
                  <p className="detail-hint">No submissions yet.</p>
                ) : (
                  <table className="leaderboard-table">
                    <thead>
                      <tr>
                        <th>Rank</th>
                        <th>Student</th>
                        <th>Score</th>
                        <th>Percentage</th>
                        <th>Submitted</th>
                      </tr>
                    </thead>
                    <tbody>
                      {leaderboard.map(r => (
                        <tr key={r.id} className={r.rank <= 3 ? "top-rank" : ""}>
                          <td>
                            {r.rank === 1 ? "1st" : r.rank === 2 ? "2nd" : r.rank === 3 ? "3rd" : `#${r.rank}`}
                          </td>
                          <td>{names[r.student_uid]?.name || r.student_uid}</td>
                          <td>{r.score} / {r.total}</td>
                          <td>
                            <div className="score-container">
                              <div className="score-bar-wrap">
                                <div className="score-bar-fill" style={{ width: `${r.percentage}%` }} />
                              </div>
                              <span className="score-text">{r.percentage}%</span>
                            </div>
                          </td>
                          <td className="ts-cell">
                            {r.submitted_at?.toDate
                              ? r.submitted_at.toDate().toLocaleDateString()
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>
            </div>
          </div>
        )}
      </main>

      {/* ── Create Course Modal ──────────────────────────────── */}
      {showCreateCourse && (
        <div className="modal-overlay" onClick={() => setShowCreateCourse(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2>Create Course</h2>
            <form onSubmit={handleCreateCourse}>
              <div className="field">
                <label>Course Name</label>
                <input
                  type="text"
                  placeholder="e.g. AWS Cloud Architect"
                  value={courseName}
                  onChange={e => setCourseName(e.target.value)}
                  autoFocus
                />
              </div>
              <div className="modal-actions">
                <button type="button" className="modal-cancel" onClick={() => setShowCreateCourse(false)}>
                  Cancel
                </button>
                <button type="submit" className="action-btn" disabled={saving}>
                  {saving ? "Creating..." : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Create Exam Modal ────────────────────────────────── */}
      {showCreateExam && (
        <div className="modal-overlay" onClick={() => setShowCreateExam(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2>Create Exam</h2>
            <form onSubmit={handleCreateExam}>
              <div className="field">
                <label>Exam Title</label>
                <input
                  type="text"
                  placeholder="e.g. AWS CAD - Module 1 Quiz"
                  value={examTitle}
                  onChange={e => setExamTitle(e.target.value)}
                  autoFocus
                />
              </div>
              <div className="field-row">
                <div className="field">
                  <label>Questions to Pick</label>
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={examPickN}
                    onChange={e => setExamPickN(e.target.value)}
                  />
                </div>
                <div className="field">
                  <label>Duration (minutes)</label>
                  <input
                    type="number"
                    min={1}
                    max={180}
                    value={examDuration}
                    onChange={e => setExamDuration(e.target.value)}
                  />
                </div>
              </div>
              <div className="modal-actions">
                <button type="button" className="modal-cancel" onClick={() => setShowCreateExam(false)}>
                  Cancel
                </button>
                <button type="submit" className="action-btn" disabled={saving}>
                  {saving ? "Creating..." : "Create Exam"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
