// src/api/examApi.js — Firestore helpers for the exam platform

import {
  collection, doc, setDoc, getDoc, getDocs,
  addDoc, updateDoc, deleteDoc,
  query, where, orderBy, serverTimestamp,
} from "firebase/firestore";
import { db } from "../firebase";

/* ─────────────────────────────────────────────────────────────
   COURSES
───────────────────────────────────────────────────────────── */

/** Create a new course (mentor only) */
export async function createCourse({ name, mentorUid }) {
  const ref = await addDoc(collection(db, "courses"), {
    name,
    mentor_uid: mentorUid,
    created_at: serverTimestamp(),
  });
  return ref.id;
}

/** Get all courses */
export async function getAllCourses() {
  const snap = await getDocs(collection(db, "courses"));
  return snap.docs.map(d => ({ id: d.id, ...d.data() }));
}

/** Get courses created by a specific mentor */
export async function getMentorCourses(mentorUid) {
  const q = query(collection(db, "courses"), where("mentor_uid", "==", mentorUid));
  const snap = await getDocs(q);
  return snap.docs.map(d => ({ id: d.id, ...d.data() }));
}

/* ─────────────────────────────────────────────────────────────
   ENROLLMENTS
───────────────────────────────────────────────────────────── */

/** Enroll a student in a course */
export async function enrollStudent(courseId, studentUid) {
  const id = `${courseId}__${studentUid}`;
  await setDoc(doc(db, "enrollments", id), {
    student_uid: studentUid,
    course_id: courseId,
    enrolled_at: serverTimestamp(),
  });
}

/** Get all course IDs a student is enrolled in */
export async function getStudentEnrollments(studentUid) {
  const q = query(collection(db, "enrollments"), where("student_uid", "==", studentUid));
  const snap = await getDocs(q);
  return snap.docs.map(d => d.data().course_id);
}

/** Check if student is enrolled in a course */
export async function isEnrolled(courseId, studentUid) {
  const snap = await getDoc(doc(db, "enrollments", `${courseId}__${studentUid}`));
  return snap.exists();
}

/** Get all students enrolled in a course */
export async function getCourseStudents(courseId) {
  const q = query(collection(db, "enrollments"), where("course_id", "==", courseId));
  const snap = await getDocs(q);
  return snap.docs.map(d => d.data().student_uid);
}

/* ─────────────────────────────────────────────────────────────
   EXAMS
───────────────────────────────────────────────────────────── */

/** Create an exam under a course */
export async function createExam({ courseId, title, pickN, durationSec, mentorUid }) {
  const ref = await addDoc(collection(db, "exams"), {
    course_id: courseId,
    title,
    pick_n: Number(pickN),
    duration_sec: Number(durationSec),
    total_q: 0,
    is_live: false,
    created_by: mentorUid,
    created_at: serverTimestamp(),
  });
  return ref.id;
}

/** Get all exams for a course */
export async function getCourseExams(courseId) {
  const q = query(collection(db, "exams"), where("course_id", "==", courseId));
  const snap = await getDocs(q);
  return snap.docs.map(d => ({ id: d.id, ...d.data() }));
}

/** Get a single exam */
export async function getExam(examId) {
  const snap = await getDoc(doc(db, "exams", examId));
  return snap.exists() ? { id: snap.id, ...snap.data() } : null;
}

/** Toggle exam live status */
export async function setExamLive(examId, isLive) {
  await updateDoc(doc(db, "exams", examId), { is_live: isLive });
}

/* ─────────────────────────────────────────────────────────────
   QUESTIONS
───────────────────────────────────────────────────────────── */

/**
 * Upload questions from parsed Excel rows to Firestore.
 * rows: Array of { question, opt_a, opt_b, opt_c, opt_d, correct, topic }
 */
export async function uploadQuestions(examId, rows) {
  const bankRef = collection(db, "questions", examId, "bank");

  // Delete existing questions first (clean re-upload)
  const existing = await getDocs(bankRef);
  const deletes = existing.docs.map(d => deleteDoc(d.ref));
  await Promise.all(deletes);

  // Write new questions
  const writes = rows.map(row =>
    addDoc(bankRef, {
      question: row.question,
      opt_a: row.opt_a,
      opt_b: row.opt_b,
      opt_c: row.opt_c,
      opt_d: row.opt_d,
      correct: String(row.correct).toUpperCase().trim(),
      topic: row.topic || "General",
    })
  );
  await Promise.all(writes);

  // Update total_q count on exam doc
  await updateDoc(doc(db, "exams", examId), { total_q: rows.length });

  return rows.length;
}

/** Get all questions in an exam's bank */
export async function getQuestionBank(examId) {
  const snap = await getDocs(collection(db, "questions", examId, "bank"));
  return snap.docs.map(d => ({ id: d.id, ...d.data() }));
}

/* ─────────────────────────────────────────────────────────────
   STUDENT EXAM SESSIONS
───────────────────────────────────────────────────────────── */

/**
 * Assign a random subset of questions to a student for an exam.
 * Returns the assigned question objects.
 */
export async function assignQuestionsToStudent(examId, studentUid, pickN) {
  const docId = `${examId}__${studentUid}`;

  // Check if already assigned
  const existing = await getDoc(doc(db, "student_exams", docId));
  if (existing.exists()) {
    // Already assigned — return existing assignment
    const bank = await getQuestionBank(examId);
    const ids = existing.data().question_ids;
    return bank.filter(q => ids.includes(q.id));
  }

  // Get full question bank
  const bank = await getQuestionBank(examId);

  // Shuffle and pick N
  const shuffled = [...bank].sort(() => Math.random() - 0.5);
  const picked = shuffled.slice(0, Math.min(pickN, shuffled.length));

  // Save assignment to Firestore
  await setDoc(doc(db, "student_exams", docId), {
    question_ids: picked.map(q => q.id),
    answers: {},
    submitted: false,
    started_at: serverTimestamp(),
    submitted_at: null,
    score: null,
    topic_scores: {},
  });

  return picked;
}

/** Save a student's answer for one question */
export async function saveAnswer(examId, studentUid, questionId, answer) {
  const docId = `${examId}__${studentUid}`;
  await updateDoc(doc(db, "student_exams", docId), {
    [`answers.${questionId}`]: answer,
  });
}

/** Get student's exam session (answers, submitted status, etc.) */
export async function getStudentExamSession(examId, studentUid) {
  const snap = await getDoc(doc(db, "student_exams", `${examId}__${studentUid}`));
  return snap.exists() ? snap.data() : null;
}

/* ─────────────────────────────────────────────────────────────
   RESULTS
───────────────────────────────────────────────────────────── */

/**
 * Submit and evaluate an exam.
 * Calculates score, topic breakdown, stores result.
 */
export async function submitExam(examId, studentUid) {
  const sessionRef = doc(db, "student_exams", `${examId}__${studentUid}`);
  const sessionSnap = await getDoc(sessionRef);
  if (!sessionSnap.exists()) throw new Error("Session not found");

  const session = sessionSnap.data();
  if (session.submitted) return; // Already submitted

  const bank = await getQuestionBank(examId);
  const questionMap = Object.fromEntries(bank.map(q => [q.id, q]));

  const { answers, question_ids } = session;
  let correct = 0;
  const topicScores = {};

  for (const qId of question_ids) {
    const q = questionMap[qId];
    if (!q) continue;
    const topic = q.topic || "General";
    if (!topicScores[topic]) topicScores[topic] = { correct: 0, total: 0 };
    topicScores[topic].total += 1;

    if (answers[qId] === q.correct) {
      correct += 1;
      topicScores[topic].correct += 1;
    }
  }

  const total = question_ids.length;
  const percentage = total > 0 ? Math.round((correct / total) * 100) : 0;

  // Update student_exams doc
  await updateDoc(sessionRef, {
    submitted: true,
    submitted_at: serverTimestamp(),
    score: correct,
    topic_scores: topicScores,
  });

  // Fetch exam title
  const examSnap = await getDoc(doc(db, "exams", examId));
  const examTitle = examSnap.exists() ? examSnap.data().title : "Exam";

  // Write to results collection
  await setDoc(doc(db, "results", `${examId}__${studentUid}`), {
    exam_id: examId,
    student_uid: studentUid,
    exam_title: examTitle,
    score: correct,
    total,
    percentage,
    topic_scores: topicScores,
    submitted_at: serverTimestamp(),
  });

  return { score: correct, total, percentage, topicScores };
}

/** Get a student's result for a specific exam */
export async function getResult(examId, studentUid) {
  const snap = await getDoc(doc(db, "results", `${examId}__${studentUid}`));
  return snap.exists() ? { id: snap.id, ...snap.data() } : null;
}

/** Get all results for a student (exam history) */
export async function getStudentHistory(studentUid) {
  // Sorted client-side to avoid needing a Firestore composite index
  const q = query(collection(db, "results"), where("student_uid", "==", studentUid));
  const snap = await getDocs(q);
  const ms = r => r.submitted_at?.toMillis?.() ?? 0;
  return snap.docs.map(d => ({ id: d.id, ...d.data() })).sort((a, b) => ms(b) - ms(a));
}

/** Get all results for an exam (for leaderboard) */
export async function getExamLeaderboard(examId) {
  const q = query(
    collection(db, "results"),
    where("exam_id", "==", examId),
    orderBy("percentage", "desc")
  );
  const snap = await getDocs(q);
  return snap.docs.map((d, i) => ({ id: d.id, rank: i + 1, ...d.data() }));
}
