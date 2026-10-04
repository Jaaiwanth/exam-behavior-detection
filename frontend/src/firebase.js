// src/firebase.js — Firebase app initialization
import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

const firebaseConfig = {
  apiKey: "AIzaSyB1uxt6K7ouwGK5acEg4B6FPAPHHhRJTns",
  authDomain: "exam-proctor-31750.firebaseapp.com",
  projectId: "exam-proctor-31750",
  storageBucket: "exam-proctor-31750.firebasestorage.app",
  messagingSenderId: "369713115500",
  appId: "1:369713115500:web:b2df69fb2a01f752a6c349",
  measurementId: "G-Y7LX7F21PC",
};

const app = initializeApp(firebaseConfig);

export const auth = getAuth(app);
export const db = getFirestore(app);
export default app;
