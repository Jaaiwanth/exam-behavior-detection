// src/main.jsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import StudentExam from "./pages/StudentExam.jsx";
import FacultyDashboard from "./pages/FacultyDashboard.jsx";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <BrowserRouter>
    <Routes>
      <Route path="/" element={<StudentExam studentId="s001" />} />
      <Route path="/faculty" element={<FacultyDashboard studentId="s001" />} />
    </Routes>
  </BrowserRouter>
);
