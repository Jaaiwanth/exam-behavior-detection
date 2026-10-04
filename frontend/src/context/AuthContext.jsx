// src/context/AuthContext.jsx
import React, { createContext, useContext, useEffect, useState } from "react";
import { onAuthStateChanged } from "firebase/auth";
import { doc, getDoc } from "firebase/firestore";
import { auth, db } from "../firebase";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser]       = useState(null);
  const [role, setRole]       = useState(null);   // "student" | "mentor" | "pending" | "admin"
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const unsub = onAuthStateChanged(auth, async (firebaseUser) => {
      if (firebaseUser) {
        // Hold the route guards until the role is fetched, so they never
        // see a signed-in user with a missing or stale role.
        setLoading(true);
        let fetchedRole = null;
        try {
          const snap = await getDoc(doc(db, "users", firebaseUser.uid));
          if (snap.exists()) fetchedRole = snap.data().role;
        } catch (err) {
          console.error("Failed to fetch user role:", err);
        }
        setRole(fetchedRole);
        setUser(firebaseUser);
      } else {
        setUser(null);
        setRole(null);
      }
      setLoading(false);
    });
    return unsub;
  }, []);

  return (
    <AuthContext.Provider value={{ user, role, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
