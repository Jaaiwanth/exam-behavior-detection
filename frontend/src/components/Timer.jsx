/* src/components/Timer.jsx — Countdown to an absolute end time (survives page refresh) */
import React, { useEffect, useRef, useState } from "react";

const fmt = (s) => {
  const m = Math.floor(s / 60).toString().padStart(2, "0");
  const sec = (s % 60).toString().padStart(2, "0");
  return `${m}:${sec}`;
};

/**
 * @param {number}   endsAt    epoch ms when the exam ends
 * @param {function} onExpire  called once when the countdown reaches zero
 */
export default function Timer({ endsAt, onExpire }) {
  const calc = () => Math.max(0, Math.round((endsAt - Date.now()) / 1000));
  const [left, setLeft] = useState(calc);
  const expired = useRef(false);
  const onExpireRef = useRef(onExpire);
  useEffect(() => { onExpireRef.current = onExpire; });

  useEffect(() => {
    expired.current = false;
    const tick = () => {
      const s = Math.max(0, Math.round((endsAt - Date.now()) / 1000));
      setLeft(s);
      if (s <= 0 && !expired.current) {
        expired.current = true;
        onExpireRef.current?.();
      }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [endsAt]);

  return (
    <span
      className="exam-timer"
      style={{ color: left < 60 ? "var(--danger)" : left < 300 ? "var(--warn)" : "var(--text-primary)" }}
    >
      {fmt(left)}
    </span>
  );
}
