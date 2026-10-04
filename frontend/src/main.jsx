// src/main.jsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";

import LandingPage      from "./pages/LandingPage.jsx";
import StudentAuth      from "./pages/StudentAuth.jsx";
import MentorAuth       from "./pages/MentorAuth.jsx";
import AdminApproval    from "./pages/AdminApproval.jsx";
import StudentDashboard from "./pages/StudentDashboard.jsx";
import MentorDashboard  from "./pages/MentorDashboard.jsx";
import StudentHistory   from "./pages/StudentHistory.jsx";
import "./index.css";

// Protected route — redirects to landing if not logged in
function ProtectedRoute({ children, allowedRoles }) {
  const { user, role, loading } = useAuth();
  if (loading) return <div className="loading-spinner">Loading...</div>;
  if (!user)   return <Navigate to="/" replace />;
  if (allowedRoles && !allowedRoles.includes(role)) return <Navigate to="/" replace />;
  return children;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <AuthProvider>
    <BrowserRouter>
      <Routes>
        {/* Public */}
        <Route path="/"               element={<LandingPage />} />
        <Route path="/student/login"  element={<StudentAuth />} />
        <Route path="/mentor/login"   element={<MentorAuth />} />

        {/* Admin only */}
        <Route
          path="/admin"
          element={
            <ProtectedRoute allowedRoles={["admin"]}>
              <AdminApproval />
            </ProtectedRoute>
          }
        />

        {/* Student only */}
        <Route
          path="/student/dashboard"
          element={
            <ProtectedRoute allowedRoles={["student"]}>
              <StudentDashboard />
            </ProtectedRoute>
          }
        />

        <Route
          path="/student/history"
          element={
            <ProtectedRoute allowedRoles={["student"]}>
              <StudentHistory />
            </ProtectedRoute>
          }
        />

        {/* Mentor / Admin */}
        <Route
          path="/mentor/dashboard"
          element={
            <ProtectedRoute allowedRoles={["mentor", "admin"]}>
              <MentorDashboard />
            </ProtectedRoute>
          }
        />

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </AuthProvider>
);
