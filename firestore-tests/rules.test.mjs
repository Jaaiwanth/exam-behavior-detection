// Emulator tests for ../firestore.rules.
// Every "app flow" test performs the SAME Firestore call the frontend makes (see frontend/src/api/examApi.js
// and the pages); every "attack" test is something a malicious user could try from the browser console.
//
//   cd firestore-tests && npm install && npm test

import { readFileSync } from "node:fs";
import { describe, it, before, after, beforeEach } from "node:test";
import {
  initializeTestEnvironment, assertSucceeds, assertFails,
} from "@firebase/rules-unit-testing";
import {
  doc, getDoc, getDocs, setDoc, addDoc, updateDoc, deleteDoc,
  collection, query, where, serverTimestamp,
} from "firebase/firestore";

let env;
before(async () => {
  env = await initializeTestEnvironment({
    projectId: "demo-examproctor",
    firestore: { rules: readFileSync(new URL("../firestore.rules", import.meta.url), "utf8"), host: "127.0.0.1", port: 8080 },
  });
});
after(async () => { await env.cleanup(); });

const as = (uid) => env.authenticatedContext(uid, { email: `${uid}@college.edu` }).firestore();
const anon = () => env.unauthenticatedContext().firestore();

const ISO = "2026-10-04T00:00:00.000Z";
const T = new Date(ISO);

async function seed() {
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    const put = (path, data) => setDoc(doc(db, path), data);
    const user = (id, role, extra = {}) => put(`users/${id}`, { name: id, email: `${id}@college.edu`, role, created_at: ISO, ...extra });
    await user("admin1", "admin");
    await user("mA", "mentor");
    await user("mB", "mentor");
    await user("s1", "student", { reg_no: "REG1" });
    await user("s2", "student", { reg_no: "REG2" });
    await user("s3", "student", { reg_no: "REG3" });     // not enrolled anywhere
    await user("pm1", "pending");
    await put("pending_mentors/pm1", { name: "pm1", email: "pm1@college.edu", uid: "pm1", requested_at: ISO, status: "pending" });

    await put("courses/cA", { name: "Course A", mentor_uid: "mA", created_at: T });
    await put("courses/cB", { name: "Course B", mentor_uid: "mB", created_at: T });
    await put("enrollments/cA__s1", { student_uid: "s1", course_id: "cA", enrolled_at: T });
    await put("enrollments/cA__s2", { student_uid: "s2", course_id: "cA", enrolled_at: T });
    await put("enrollments/cB__s3", { student_uid: "s3", course_id: "cB", enrolled_at: T });

    const exam = (id, course, owner, live) => put(`exams/${id}`, {
      course_id: course, title: id, pick_n: 2, duration_sec: 600, total_q: 3,
      is_live: live, created_by: owner, created_at: T });
    await exam("eLive", "cA", "mA", true);
    await exam("eDraft", "cA", "mA", false);
    await exam("eB", "cB", "mB", true);
    for (const e of ["eLive", "eDraft", "eB"]) {
      for (const q of ["q1", "q2", "q3"]) {
        await put(`questions/${e}/bank/${q}`, { question: "Q?", opt_a: "a", opt_b: "b", opt_c: "c", opt_d: "d", correct: "A", topic: "T" });
      }
    }
    // s1 has started eLive; s2 has finished it
    await put("student_exams/eLive__s1", { question_ids: ["q1", "q2"], answers: {}, submitted: false, started_at: T, submitted_at: null, score: null, topic_scores: {} });
    await put("student_exams/eLive__s2", { question_ids: ["q1", "q2"], answers: { q1: "A", q2: "B" }, submitted: true, started_at: T, submitted_at: T, score: 1, topic_scores: { T: { correct: 1, total: 2 } } });
    await put("results/eLive__s2", { exam_id: "eLive", student_uid: "s2", exam_title: "eLive", score: 1, total: 2, percentage: 50, topic_scores: {}, submitted_at: T });
    await put("results/eB__s3", { exam_id: "eB", student_uid: "s3", exam_title: "eB", score: 2, total: 3, percentage: 67, topic_scores: {}, submitted_at: T });
  });
}
beforeEach(seed);

// ════════════════════════════════════════════════════════════════════════════
describe("unauthenticated access", () => {
  it("is denied on every collection", async () => {
    const db = anon();
    for (const path of ["users/s1", "courses/cA", "exams/eLive", "enrollments/cA__s1", "student_exams/eLive__s1",
                        "results/eLive__s2", "pending_mentors/pm1", "questions/eLive/bank/q1", "anything/x"]) {
      await assertFails(getDoc(doc(db, path)));
    }
    await assertFails(getDocs(collection(db, "users")));
    await assertFails(getDocs(collection(db, "courses")));
    await assertFails(getDocs(collection(db, "questions", "eLive", "bank")));
  });
  it("cannot write anything", async () => {
    const db = anon();
    await assertFails(setDoc(doc(db, "users/x"), { name: "x", email: "x@y.z", role: "student", reg_no: "R", created_at: ISO }));
    await assertFails(addDoc(collection(db, "courses"), { name: "x" }));
  });
  it("may read ONLY reg_map/{id} by id (the login lookup) — no listing, no writes", async () => {
    await assertSucceeds(getDoc(doc(anon(), "reg_map/REG1")));
    await assertFails(getDocs(collection(anon(), "reg_map")));
    await assertFails(setDoc(doc(anon(), "reg_map/REG1"), { email: "a@b.c" }));
    await assertFails(setDoc(doc(as("s1"), "reg_map/REG1"), { email: "a@b.c" }));
  });
});

// ════════════════════════════════════════════════════════════════════════════
describe("users", () => {
  it("signup: a student can create their own student profile (StudentAuth.jsx)", async () => {
    await assertSucceeds(setDoc(doc(as("new1"), "users/new1"), { name: "N", reg_no: "R9", email: "new1@college.edu", role: "student", created_at: ISO }));
  });
  it("signup: a mentor applicant creates a pending profile + request (MentorAuth.jsx)", async () => {
    const db = as("new2");
    await assertSucceeds(setDoc(doc(db, "users/new2"), { name: "M", email: "new2@college.edu", role: "pending", created_at: ISO }));
    await assertSucceeds(setDoc(doc(db, "pending_mentors/new2"), { name: "M", email: "new2@college.edu", uid: "new2", requested_at: ISO, status: "pending" }));
  });
  it("signup: mixed-case email typed by the user still matches the auth email", async () => {
    await assertSucceeds(setDoc(doc(as("new3"), "users/new3"), { name: "N", reg_no: "R", email: "New3@College.EDU", role: "student", created_at: ISO }));
  });
  it("ATTACK: cannot self-register as mentor or admin", async () => {
    for (const role of ["mentor", "admin", "rejected"]) {
      await assertFails(setDoc(doc(as("evil"), "users/evil"), { name: "E", email: "evil@college.edu", role, created_at: ISO }));
    }
  });
  it("ATTACK: cannot create a profile with a different email, an extra field, or for another uid", async () => {
    await assertFails(setDoc(doc(as("evil"), "users/evil"), { name: "E", reg_no: "R", email: "victim@college.edu", role: "student", created_at: ISO }));
    await assertFails(setDoc(doc(as("evil"), "users/evil"), { name: "E", reg_no: "R", email: "evil@college.edu", role: "student", created_at: ISO, isAdmin: true }));
    await assertFails(setDoc(doc(as("evil"), "users/someoneelse"), { name: "E", reg_no: "R", email: "evil@college.edu", role: "student", created_at: ISO }));
  });
  it("a user reads their own profile (AuthContext) incl. a profile that does not exist yet", async () => {
    await assertSucceeds(getDoc(doc(as("s1"), "users/s1")));
    await assertSucceeds(getDoc(doc(as("brandnew"), "users/brandnew")));
  });
  it("ATTACK: a student cannot read another student's, a mentor's or the admin's profile", async () => {
    for (const id of ["s2", "mA", "admin1"]) await assertFails(getDoc(doc(as("s1"), `users/${id}`)));
    await assertFails(getDocs(collection(as("s1"), "users")));
  });
  it("ATTACK: a user cannot change their own role (student -> admin, mentor -> admin, pending -> mentor)", async () => {
    await assertFails(updateDoc(doc(as("s1"), "users/s1"), { role: "admin" }));
    await assertFails(updateDoc(doc(as("mA"), "users/mA"), { role: "admin" }));
    await assertFails(updateDoc(doc(as("pm1"), "users/pm1"), { role: "mentor" }));
  });
  it("ATTACK: a student cannot change their email or registration number", async () => {
    await assertFails(updateDoc(doc(as("s1"), "users/s1"), { email: "other@college.edu" }));
    await assertFails(updateDoc(doc(as("s1"), "users/s1"), { reg_no: "REG2" }));
    await assertSucceeds(updateDoc(doc(as("s1"), "users/s1"), { name: "New Name" }));   // the only allowed edit
  });
  it("ATTACK: a student cannot edit another user", async () => {
    await assertFails(updateDoc(doc(as("s1"), "users/s2"), { name: "hacked" }));
  });
  it("nobody can delete a profile", async () => {
    await assertFails(deleteDoc(doc(as("s1"), "users/s1")));
    await assertFails(deleteDoc(doc(as("admin1"), "users/s1")));
  });
  it("mentor: reads STUDENT profiles (get + the findStudent queries) but not mentor/admin profiles", async () => {
    const db = as("mA");
    await assertSucceeds(getDoc(doc(db, "users/s1")));
    await assertSucceeds(getDocs(query(collection(db, "users"), where("email", "==", "s3@college.edu"), where("role", "==", "student"))));
    await assertSucceeds(getDocs(query(collection(db, "users"), where("reg_no", "==", "REG3"), where("role", "==", "student"))));
    await assertFails(getDoc(doc(db, "users/mB")));
    await assertFails(getDoc(doc(db, "users/admin1")));
    await assertFails(getDocs(collection(db, "users")));                                       // no unfiltered dump
    await assertFails(getDocs(query(collection(db, "users"), where("email", "==", "mB@college.edu"))));   // role filter is mandatory
  });
  it("admin: reads any profile; may move a PENDING mentor to mentor/rejected only (AdminApproval.jsx)", async () => {
    const db = as("admin1");
    await assertSucceeds(getDoc(doc(db, "users/pm1")));
    await assertSucceeds(updateDoc(doc(db, "users/pm1"), { role: "mentor" }));
    await assertFails(updateDoc(doc(db, "users/s1"), { role: "mentor" }));                     // not a pending mentor
    await assertFails(updateDoc(doc(db, "users/s1"), { role: "admin" }));
    await assertFails(updateDoc(doc(db, "users/mA"), { name: "x" }));                          // admin cannot rewrite others' data
  });
  it("admin rejection works", async () => {
    await assertSucceeds(updateDoc(doc(as("admin1"), "users/pm1"), { role: "rejected" }));
  });
});

// ════════════════════════════════════════════════════════════════════════════
describe("pending_mentors", () => {
  it("admin lists and approves/rejects (AdminApproval.jsx)", async () => {
    const db = as("admin1");
    await assertSucceeds(getDocs(collection(db, "pending_mentors")));
    await assertSucceeds(updateDoc(doc(db, "pending_mentors/pm1"), { status: "approved" }));
  });
  it("ATTACK: non-admins cannot list; applicants cannot approve themselves", async () => {
    await assertFails(getDocs(collection(as("pm1"), "pending_mentors")));
    await assertFails(getDocs(collection(as("mA"), "pending_mentors")));
    await assertFails(updateDoc(doc(as("pm1"), "pending_mentors/pm1"), { status: "approved" }));
    await assertSucceeds(getDoc(doc(as("pm1"), "pending_mentors/pm1")));                       // may read their own request
    await assertFails(getDoc(doc(as("s1"), "pending_mentors/pm1")));
  });
  it("ATTACK: a student cannot file a mentor request, nor a request pre-approved / for someone else", async () => {
    await assertFails(setDoc(doc(as("s1"), "pending_mentors/s1"), { name: "s1", email: "s1@college.edu", uid: "s1", requested_at: ISO, status: "pending" }));
    await seed();
    await assertFails(setDoc(doc(as("new9"), "pending_mentors/new9"), { name: "x", email: "new9@college.edu", uid: "new9", requested_at: ISO, status: "approved" }));
    await assertFails(setDoc(doc(as("new9"), "pending_mentors/other"), { name: "x", email: "new9@college.edu", uid: "other", requested_at: ISO, status: "pending" }));
  });
});

// ════════════════════════════════════════════════════════════════════════════
describe("courses", () => {
  it("mentor creates their own course, lists their own courses (examApi.js createCourse / getMentorCourses)", async () => {
    const db = as("mA");
    await assertSucceeds(addDoc(collection(db, "courses"), { name: "New", mentor_uid: "mA", created_at: serverTimestamp() }));
    await assertSucceeds(getDocs(query(collection(db, "courses"), where("mentor_uid", "==", "mA"))));
  });
  it("ATTACK: cannot create a course owned by someone else, or as a student", async () => {
    await assertFails(addDoc(collection(as("mA"), "courses"), { name: "x", mentor_uid: "mB", created_at: serverTimestamp() }));
    await assertFails(addDoc(collection(as("s1"), "courses"), { name: "x", mentor_uid: "s1", created_at: serverTimestamp() }));
  });
  it("ATTACK: another mentor cannot edit, delete, take over or read my course", async () => {
    const db = as("mB");
    await assertFails(updateDoc(doc(db, "courses/cA"), { name: "hijack" }));
    await assertFails(updateDoc(doc(db, "courses/cA"), { mentor_uid: "mB" }));
    await assertFails(deleteDoc(doc(db, "courses/cA")));
    await assertFails(getDoc(doc(db, "courses/cA")));
    await assertFails(getDocs(query(collection(db, "courses"), where("mentor_uid", "==", "mA"))));
  });
  it("owner may rename but not reassign; admin may manage", async () => {
    await assertSucceeds(updateDoc(doc(as("mA"), "courses/cA"), { name: "Renamed" }));
    await assertFails(updateDoc(doc(as("mA"), "courses/cA"), { mentor_uid: "mB" }));
    await assertSucceeds(getDoc(doc(as("admin1"), "courses/cA")));
    await assertSucceeds(updateDoc(doc(as("admin1"), "courses/cA"), { name: "By admin" }));
  });
  it("student: reads only courses they are enrolled in (by id); cannot list all courses", async () => {
    const db = as("s1");
    await assertSucceeds(getDoc(doc(db, "courses/cA")));
    await assertFails(getDoc(doc(db, "courses/cB")));
    await assertFails(getDocs(collection(db, "courses")));                                     // old getAllCourses()
    await assertFails(updateDoc(doc(db, "courses/cA"), { name: "x" }));
    await assertFails(deleteDoc(doc(db, "courses/cA")));
  });
});

// ════════════════════════════════════════════════════════════════════════════
describe("enrollments (mentor-managed)", () => {
  it("mentor adds, lists and removes students in their own course", async () => {
    const db = as("mA");
    await assertSucceeds(setDoc(doc(db, "enrollments/cA__s3"), { student_uid: "s3", course_id: "cA", enrolled_at: serverTimestamp() }));
    await assertSucceeds(getDocs(query(collection(db, "enrollments"), where("course_id", "==", "cA"))));
    await assertSucceeds(setDoc(doc(db, "enrollments/cA__s3"), { student_uid: "s3", course_id: "cA", enrolled_at: serverTimestamp() }));  // re-add
    await assertSucceeds(deleteDoc(doc(db, "enrollments/cA__s1")));
  });
  it("ATTACK: students cannot enroll themselves or others, or remove an enrollment", async () => {
    await assertFails(setDoc(doc(as("s3"), "enrollments/cA__s3"), { student_uid: "s3", course_id: "cA", enrolled_at: serverTimestamp() }));
    await assertFails(setDoc(doc(as("s1"), "enrollments/cB__s1"), { student_uid: "s1", course_id: "cB", enrolled_at: serverTimestamp() }));
    await assertFails(deleteDoc(doc(as("s1"), "enrollments/cA__s1")));
  });
  it("ATTACK: another mentor cannot manage or read my course's enrollments", async () => {
    const db = as("mB");
    await assertFails(setDoc(doc(db, "enrollments/cA__s3"), { student_uid: "s3", course_id: "cA", enrolled_at: serverTimestamp() }));
    await assertFails(deleteDoc(doc(db, "enrollments/cA__s1")));
    await assertFails(getDocs(query(collection(db, "enrollments"), where("course_id", "==", "cA"))));
    await assertFails(getDoc(doc(db, "enrollments/cA__s1")));
  });
  it("ATTACK: cannot enroll a non-student, or forge mismatched fields", async () => {
    const db = as("mA");
    await assertFails(setDoc(doc(db, "enrollments/cA__mB"), { student_uid: "mB", course_id: "cA", enrolled_at: serverTimestamp() }));
    await assertFails(setDoc(doc(db, "enrollments/cA__s3"), { student_uid: "s2", course_id: "cA", enrolled_at: serverTimestamp() }));
    await assertFails(setDoc(doc(db, "enrollments/cA__s3"), { student_uid: "s3", course_id: "cB", enrolled_at: serverTimestamp() }));
  });
  it("student reads only their own enrollments (getStudentEnrollments / isEnrolled)", async () => {
    const db = as("s1");
    await assertSucceeds(getDocs(query(collection(db, "enrollments"), where("student_uid", "==", "s1"))));
    await assertSucceeds(getDoc(doc(db, "enrollments/cA__s1")));
    await assertSucceeds(getDoc(doc(db, "enrollments/cB__s1")));                               // not enrolled: "not found", not an error
    await assertFails(getDoc(doc(db, "enrollments/cA__s2")));
    await assertFails(getDocs(query(collection(db, "enrollments"), where("student_uid", "==", "s2"))));
    await assertFails(getDocs(query(collection(db, "enrollments"), where("course_id", "==", "cA"))));
  });
});

// ════════════════════════════════════════════════════════════════════════════
describe("exams", () => {
  const newExam = (course, extra = {}) => ({
    course_id: course, title: "T", pick_n: 5, duration_sec: 600, total_q: 0, is_live: false,
    created_by: "mA", created_at: serverTimestamp(), ...extra });

  it("mentor creates an exam in their own course and lists exams (createExam / getCourseExams)", async () => {
    const db = as("mA");
    await assertSucceeds(addDoc(collection(db, "exams"), newExam("cA")));
    await assertSucceeds(getDocs(query(collection(db, "exams"), where("course_id", "==", "cA"))));
    await assertSucceeds(getDoc(doc(db, "exams/eLive")));
  });
  it("ATTACK: a mentor cannot create an exam in someone else's course, or spoof created_by", async () => {
    await assertFails(addDoc(collection(as("mA"), "exams"), newExam("cB")));
    await assertFails(addDoc(collection(as("mA"), "exams"), newExam("cA", { created_by: "mB" })));
    await assertFails(addDoc(collection(as("mA"), "exams"), newExam("cA", { is_live: true })));
  });
  it("ATTACK: students cannot create or edit exams", async () => {
    await assertFails(addDoc(collection(as("s1"), "exams"), { ...newExam("cA"), created_by: "s1" }));
    await assertFails(updateDoc(doc(as("s1"), "exams/eLive"), { is_live: false }));
    await assertFails(updateDoc(doc(as("s1"), "exams/eDraft"), { is_live: true }));
    await assertFails(deleteDoc(doc(as("s1"), "exams/eLive")));
  });
  it("owner toggles is_live / total_q (setExamLive, uploadQuestions) but cannot change anything else", async () => {
    const db = as("mA");
    await assertSucceeds(updateDoc(doc(db, "exams/eDraft"), { is_live: true }));
    await assertSucceeds(updateDoc(doc(db, "exams/eDraft"), { total_q: 7 }));
    await assertFails(updateDoc(doc(db, "exams/eDraft"), { course_id: "cB" }));
    await assertFails(updateDoc(doc(db, "exams/eDraft"), { created_by: "mB" }));
    await assertFails(updateDoc(doc(db, "exams/eDraft"), { pick_n: 999 }));
  });
  it("ATTACK: another mentor cannot read, edit or delete my exam", async () => {
    const db = as("mB");
    await assertFails(getDoc(doc(db, "exams/eLive")));
    await assertFails(getDocs(query(collection(db, "exams"), where("course_id", "==", "cA"))));
    await assertFails(updateDoc(doc(db, "exams/eLive"), { is_live: false }));
    await assertFails(deleteDoc(doc(db, "exams/eLive")));
  });
  it("student: sees exams of enrolled courses only (live and closed), not other courses'", async () => {
    const db = as("s1");
    await assertSucceeds(getDocs(query(collection(db, "exams"), where("course_id", "==", "cA"))));
    await assertSucceeds(getDoc(doc(db, "exams/eLive")));
    await assertSucceeds(getDoc(doc(db, "exams/eDraft")));
    await assertFails(getDoc(doc(db, "exams/eB")));
    await assertFails(getDocs(query(collection(db, "exams"), where("course_id", "==", "cB"))));
    await assertFails(getDocs(collection(db, "exams")));
  });
  it("admin has full read access", async () => {
    await assertSucceeds(getDoc(doc(as("admin1"), "exams/eB")));
  });
});

// ════════════════════════════════════════════════════════════════════════════
describe("question banks", () => {
  const qDoc = { question: "Q", opt_a: "a", opt_b: "b", opt_c: "c", opt_d: "d", correct: "B", topic: "General" };

  it("owner mentor reads, replaces (delete + create) and manages the bank (uploadQuestions)", async () => {
    const db = as("mA");
    await assertSucceeds(getDocs(collection(db, "questions", "eLive", "bank")));
    await assertSucceeds(deleteDoc(doc(db, "questions/eLive/bank/q1")));
    await assertSucceeds(addDoc(collection(db, "questions", "eLive", "bank"), qDoc));
  });
  it("ATTACK: another mentor cannot read or overwrite my question bank", async () => {
    const db = as("mB");
    await assertFails(getDocs(collection(db, "questions", "eLive", "bank")));
    await assertFails(addDoc(collection(db, "questions", "eLive", "bank"), qDoc));
    await assertFails(deleteDoc(doc(db, "questions/eLive/bank/q1")));
    await assertFails(setDoc(doc(db, "questions/eLive/bank/q1"), qDoc));
  });
  it("ATTACK: no student can write questions, enrolled or not", async () => {
    for (const s of ["s1", "s3"]) {
      await assertFails(addDoc(collection(as(s), "questions", "eLive", "bank"), qDoc));
      await assertFails(deleteDoc(doc(as(s), "questions/eLive/bank/q1")));
      await assertFails(updateDoc(doc(as(s), "questions/eLive/bank/q1"), { correct: "C" }));
    }
  });
  it("ATTACK: malformed questions are rejected (bad answer letter, extra field)", async () => {
    const db = as("mA");
    await assertFails(addDoc(collection(db, "questions", "eLive", "bank"), { ...qDoc, correct: "Z" }));
    await assertFails(addDoc(collection(db, "questions", "eLive", "bank"), { ...qDoc, evil: 1 }));
  });
  it("enrolled student reads the bank of a LIVE exam (the exam flow: assignQuestionsToStudent / getQuestionBank)", async () => {
    await assertSucceeds(getDocs(collection(as("s1"), "questions", "eLive", "bank")));
  });
  it("student cannot read a DRAFT exam's bank before it is live; can after having a session", async () => {
    await assertFails(getDocs(collection(as("s1"), "questions", "eDraft", "bank")));
    await env.withSecurityRulesDisabled(async (ctx) => {
      await updateDoc(doc(ctx.firestore(), "exams/eLive"), { is_live: false });              // exam closed afterwards
    });
    await assertSucceeds(getDocs(collection(as("s2"), "questions", "eLive", "bank")));     // s2 has a session -> result review works
  });
  it("ATTACK: students not enrolled in the course (and outsiders) cannot read the bank", async () => {
    await assertFails(getDocs(collection(as("s3"), "questions", "eLive", "bank")));
    await assertFails(getDoc(doc(as("s3"), "questions/eLive/bank/q1")));
    await assertFails(getDocs(collection(as("s1"), "questions", "eB", "bank")));
    await assertFails(getDocs(collection(as("pm1"), "questions", "eLive", "bank")));
  });
});

// ════════════════════════════════════════════════════════════════════════════
describe("student_exams", () => {
  const fresh = () => ({ question_ids: ["q1", "q2"], answers: {}, submitted: false, started_at: serverTimestamp(),
                         submitted_at: null, score: null, topic_scores: {} });

  it("enrolled student starts a live exam (assignQuestionsToStudent)", async () => {
    await env.withSecurityRulesDisabled(async (ctx) => { await deleteDoc(doc(ctx.firestore(), "student_exams/eLive__s1")); });
    const db = as("s1");
    await assertSucceeds(getDoc(doc(db, "student_exams/eLive__s1")));                          // not found, not an error
    await assertSucceeds(setDoc(doc(db, "student_exams/eLive__s1"), fresh()));
  });
  it("student saves answers (saveAnswer: updateDoc with a dotted path) and submits (submitExam)", async () => {
    const db = as("s1");
    await assertSucceeds(updateDoc(doc(db, "student_exams/eLive__s1"), { "answers.q1": "A" }));
    await assertSucceeds(updateDoc(doc(db, "student_exams/eLive__s1"), { "answers.q2": "C" }));
    await assertSucceeds(updateDoc(doc(db, "student_exams/eLive__s1"), {
      submitted: true, submitted_at: serverTimestamp(), score: 1, topic_scores: { T: { correct: 1, total: 2 } } }));
  });
  it("ATTACK: cannot start an exam you are not enrolled in, a non-live exam, or as another student", async () => {
    await assertFails(setDoc(doc(as("s3"), "student_exams/eLive__s3"), fresh()));
    await assertFails(setDoc(doc(as("s1"), "student_exams/eDraft__s1"), fresh()));
    await assertFails(setDoc(doc(as("s1"), "student_exams/eLive__s2"), fresh()));
  });
  it("ATTACK: a new session must be clean (no pre-filled answers/score, no extra fields, sane question count)", async () => {
    await env.withSecurityRulesDisabled(async (ctx) => { await deleteDoc(doc(ctx.firestore(), "student_exams/eLive__s1")); });
    const db = as("s1");
    await assertFails(setDoc(doc(db, "student_exams/eLive__s1"), { ...fresh(), score: 2 }));
    await assertFails(setDoc(doc(db, "student_exams/eLive__s1"), { ...fresh(), submitted: true }));
    await assertFails(setDoc(doc(db, "student_exams/eLive__s1"), { ...fresh(), answers: { q1: "A" } }));
    await assertFails(setDoc(doc(db, "student_exams/eLive__s1"), { ...fresh(), role: "admin" }));
    await assertFails(setDoc(doc(db, "student_exams/eLive__s1"), { ...fresh(), question_ids: ["q1", "q2", "q3"] }));   // pick_n is 2
    await assertFails(setDoc(doc(db, "student_exams/eLive__s1"), { ...fresh(), started_at: new Date("2020-01-01") }));
  });
  it("ATTACK: cannot touch other students' sessions", async () => {
    await assertFails(getDoc(doc(as("s1"), "student_exams/eLive__s2")));
    await assertFails(updateDoc(doc(as("s1"), "student_exams/eLive__s2"), { "answers.q1": "B" }));
    await assertFails(updateDoc(doc(as("s3"), "student_exams/eLive__s1"), { "answers.q1": "B" }));
    await assertFails(getDocs(collection(as("s1"), "student_exams")));
  });
  it("ATTACK: only answers/submitted/submitted_at/score/topic_scores may change; started_at, question_ids are frozen", async () => {
    const db = as("s1");
    await assertFails(updateDoc(doc(db, "student_exams/eLive__s1"), { started_at: serverTimestamp() }));      // reset the timer
    await assertFails(updateDoc(doc(db, "student_exams/eLive__s1"), { question_ids: ["q3"] }));
    await assertFails(updateDoc(doc(db, "student_exams/eLive__s1"), { reviewed_by: "me" }));
    await assertFails(updateDoc(doc(db, "student_exams/eLive__s1"), { score: 99, submitted: true, submitted_at: serverTimestamp() }));  // > question count
    await assertFails(updateDoc(doc(db, "student_exams/eLive__s1"), { submitted: true, score: 1 }));          // submitted_at must be server time
  });
  it("ATTACK: a submitted session is frozen (no un-submit, no new answers, no score edits)", async () => {
    const db = as("s2");
    await assertFails(updateDoc(doc(db, "student_exams/eLive__s2"), { submitted: false }));
    await assertFails(updateDoc(doc(db, "student_exams/eLive__s2"), { "answers.q1": "C" }));
    await assertFails(updateDoc(doc(db, "student_exams/eLive__s2"), { score: 2 }));
    await assertFails(deleteDoc(doc(db, "student_exams/eLive__s2")));
  });
  it("mentor/admin read sessions of THEIR exams only (mentor review pages)", async () => {
    await assertSucceeds(getDoc(doc(as("mA"), "student_exams/eLive__s1")));
    await assertSucceeds(getDoc(doc(as("admin1"), "student_exams/eLive__s1")));
    await assertFails(getDoc(doc(as("mB"), "student_exams/eLive__s1")));
    await assertFails(updateDoc(doc(as("mA"), "student_exams/eLive__s1"), { score: 2 }));    // mentors cannot rewrite answers
  });
});

// ════════════════════════════════════════════════════════════════════════════
describe("results", () => {
  const resultFor = (over = {}) => ({ exam_id: "eLive", student_uid: "s1", exam_title: "eLive", score: 1, total: 2,
                                       percentage: 50, topic_scores: { T: { correct: 1, total: 2 } },
                                       submitted_at: serverTimestamp(), ...over });
  const submitS1 = () => env.withSecurityRulesDisabled(async (ctx) => {
    await updateDoc(doc(ctx.firestore(), "student_exams/eLive__s1"), { submitted: true, submitted_at: T, score: 1 });
  });

  it("student writes their result once, right after submitting (submitExam)", async () => {
    await submitS1();
    await assertSucceeds(setDoc(doc(as("s1"), "results/eLive__s1"), resultFor()));
  });
  it("student reads own result + own history (getResult / getStudentHistory)", async () => {
    const db = as("s2");
    await assertSucceeds(getDoc(doc(db, "results/eLive__s2")));
    await assertSucceeds(getDocs(query(collection(db, "results"), where("student_uid", "==", "s2"))));
    await assertSucceeds(getDoc(doc(db, "results/eB__s2")));                                   // no result yet: "not found"
  });
  it("ATTACK: a student cannot read another student's result, history or an exam's leaderboard", async () => {
    const db = as("s1");
    await assertFails(getDoc(doc(db, "results/eLive__s2")));
    await assertFails(getDocs(query(collection(db, "results"), where("student_uid", "==", "s2"))));
    await assertFails(getDocs(query(collection(db, "results"), where("exam_id", "==", "eLive"))));   // old getExamLeaderboard for rank
    await assertFails(getDocs(collection(db, "results")));
  });
  it("ATTACK: cannot forge a result — before submitting, with a different score/total/percentage, or for someone else", async () => {
    const db = as("s1");
    await assertFails(setDoc(doc(db, "results/eLive__s1"), resultFor()));                      // session not submitted yet
    await submitS1();
    await assertFails(setDoc(doc(db, "results/eLive__s1"), resultFor({ score: 2, percentage: 100 })));
    await assertFails(setDoc(doc(db, "results/eLive__s1"), resultFor({ percentage: 100 })));
    await assertFails(setDoc(doc(db, "results/eLive__s1"), resultFor({ total: 1 })));
    await assertFails(setDoc(doc(db, "results/eLive__s1"), resultFor({ student_uid: "s2" })));
    await assertFails(setDoc(doc(db, "results/eLive__s2"), resultFor({ student_uid: "s2" })));
    await assertFails(setDoc(doc(db, "results/eB__s1"), resultFor({ exam_id: "eB" })));         // never took eB
    await assertFails(setDoc(doc(db, "results/eLive__s1"), { ...resultFor(), rank: 1 }));
  });
  it("ATTACK: results are immutable (no edit, no delete) — even for the owner", async () => {
    const db = as("s2");
    await assertFails(updateDoc(doc(db, "results/eLive__s2"), { score: 2, percentage: 100 }));
    await assertFails(setDoc(doc(db, "results/eLive__s2"), resultFor({ student_uid: "s2", score: 1 })));
    await assertFails(deleteDoc(doc(db, "results/eLive__s2")));
    await assertFails(updateDoc(doc(as("mA"), "results/eLive__s2"), { score: 0 }));
  });
  it("percentage: accepts what the browser computes for EVERY score/total (floating-point rounding), rejects forgery", async () => {
    // Exhaustive check that the browser's Math.round((score/total)*100) is always accepted.
    // 23/40 is the classic trap: exactly 57.5, but JavaScript yields 57.
    const trap = [[23, 40], [46, 80], [29, 200], [1, 8], [3, 8], [2, 3], [0, 5], [5, 5], [1, 3], [7, 9]];
    for (const [score, total] of trap) {
      const browserPct = Math.round((score / total) * 100);
      await seed();
      await env.withSecurityRulesDisabled(async (ctx) => {
        await updateDoc(doc(ctx.firestore(), "student_exams/eLive__s1"), {
          question_ids: Array.from({ length: total }, (_, i) => `q${i}`), submitted: true, submitted_at: T, score });
      });
      await assertSucceeds(setDoc(doc(as("s1"), "results/eLive__s1"), resultFor({ score, total, percentage: browserPct })));
    }
    await seed();
    await env.withSecurityRulesDisabled(async (ctx) => {
      await updateDoc(doc(ctx.firestore(), "student_exams/eLive__s1"), {
        question_ids: Array.from({ length: 40 }, (_, i) => `q${i}`), submitted: true, submitted_at: T, score: 23 });
    });
    await assertFails(setDoc(doc(as("s1"), "results/eLive__s1"), resultFor({ score: 23, total: 40, percentage: 59 })));
    await assertFails(setDoc(doc(as("s1"), "results/eLive__s1"), resultFor({ score: 23, total: 40, percentage: 56 })));
    await assertFails(setDoc(doc(as("s1"), "results/eLive__s1"), resultFor({ score: 23, total: 40, percentage: 100 })));
  });
  it("mentor reads the leaderboard + results of THEIR exams (getExamLeaderboard / StudentDetail getResult)", async () => {
    const db = as("mA");
    await assertSucceeds(getDocs(query(collection(db, "results"), where("exam_id", "==", "eLive"))));
    await assertSucceeds(getDoc(doc(db, "results/eLive__s2")));
    await assertSucceeds(getDoc(doc(db, "results/eDraft__s2")));                               // exists-check for a not-taken exam
  });
  it("ATTACK: another mentor cannot read my exam's results; no mentor can list a student's whole history", async () => {
    const db = as("mB");
    await assertFails(getDocs(query(collection(db, "results"), where("exam_id", "==", "eLive"))));
    await assertFails(getDoc(doc(db, "results/eLive__s2")));
    await assertFails(getDocs(query(collection(as("mA"), "results"), where("student_uid", "==", "s2"))));   // old getStudentHistory as mentor
    await assertSucceeds(getDocs(query(collection(as("mB"), "results"), where("exam_id", "==", "eB"))));
  });
  it("admin reads results", async () => {
    await assertSucceeds(getDocs(query(collection(as("admin1"), "results"), where("exam_id", "==", "eLive"))));
  });
});

// ════════════════════════════════════════════════════════════════════════════
describe("backend role lookup (backend/auth.py reads users/{uid} and exams/{id} with the CALLER's own token)", () => {
  it("every role can read its own users doc", async () => {
    for (const id of ["s1", "mA", "admin1", "pm1"]) await assertSucceeds(getDoc(doc(as(id), `users/${id}`)));
  });
  it("a mentor can read the exams they own (fetch_exam_owner) but not other mentors' exams", async () => {
    await assertSucceeds(getDoc(doc(as("mA"), "exams/eLive")));
    await assertFails(getDoc(doc(as("mB"), "exams/eLive")));
  });
});

// ════════════════════════════════════════════════════════════════════════════
describe("role matrix: a pending / rejected user has no data access", () => {
  it("pending mentor cannot do mentor things", async () => {
    const db = as("pm1");
    await assertFails(addDoc(collection(db, "courses"), { name: "x", mentor_uid: "pm1", created_at: serverTimestamp() }));
    await assertFails(getDocs(query(collection(db, "courses"), where("mentor_uid", "==", "pm1"))));
    await assertFails(getDoc(doc(db, "users/s1")));
  });
  it("a student cannot use mentor/admin queries", async () => {
    const db = as("s1");
    await assertFails(getDocs(query(collection(db, "courses"), where("mentor_uid", "==", "mA"))));
    await assertFails(getDocs(query(collection(db, "enrollments"), where("course_id", "==", "cA"))));
    await assertFails(getDocs(collection(db, "pending_mentors")));
    await assertFails(getDocs(query(collection(db, "users"), where("role", "==", "student"))));
  });
});
